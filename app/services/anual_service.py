"""Vista anual: el año entero mes a mes, como la hoja 2026_Gastos.xlsx pero viva.

Los meses cerrados muestran el gasto real; el mes en curso y los futuros, una previsión:

- si la categoría tiene presupuesto ese mes, el presupuesto (es el plan);
- si es un pago anual (Category.anual: impuestos, seguros), lo que costó el mismo mes del
  año pasado — así los recibos que solo llegan una vez al año aparecen en su mes y no
  repartidos —, y nunca menos que su presupuesto ni que lo que se paga un mes normal;
- si es recurrente, la mediana de los últimos 3 meses cerrados;
- si es variable (o sin clasificar), la media de los últimos 6 meses cerrados sin contar
  el más alto.

En el mes en curso cada celda es max(lo gastado, lo previsto): lo que va más lo que falta.

La "hucha de pagos anuales" responde a la pregunta de fondo de la hoja: cuánto apartar
cada mes, también en los meses tranquilos, para que los meses de recibos grandes no
pillen sin dinero.
"""

import statistics
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.advisor.data import category_label, load_categories, load_transactions_df
from app.models import Budget, BudgetGroup, Category
from app.services import budget_service
from app.services.dashboard_service import MONTHS_ES

MESES_MEDIA_VARIABLE = 6
MESES_MEDIANA_RECURRENTE = 3
MESES_HUCHA = 12

GRUPOS_GASTO = (BudgetGroup.NECESIDAD, BudgetGroup.DESEO, None)


# Hucha de gastos grandes (ver hucha_grandes): meses cerrados que se miran y cuánto ha de
# pasarse un mes de lo normal en una categoría para contar como gasto gordo.
MESES_GRANDES = 12
UMBRAL_PICO = 1000.0  # más bajo, cuenta como "gordo" el simple gastar de más en restaurantes


def _mes_anterior(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _mes_siguiente(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _meses_cerrados(hoy: date, n: int) -> list[tuple[int, int]]:
    """Los n meses naturales anteriores al de `hoy`, del más antiguo al más reciente."""
    meses = []
    ym = (hoy.year, hoy.month)
    for _ in range(n):
        ym = _mes_anterior(*ym)
        meses.append(ym)
    return meses[::-1]


def _gasto_por_mes(df: pd.DataFrame) -> dict[int | None, dict[tuple[int, int], float]]:
    """{category_id (None = sin clasificar): {(año, mes): gasto en € positivos}}."""
    gastos = df.loc[df["amount"] < 0].copy()
    if gastos.empty:
        return {}
    gastos["ym"] = list(zip(gastos["date"].dt.year, gastos["date"].dt.month))
    gastos["cid"] = gastos["category_id"].astype(object).where(gastos["category_id"].notna(), None)
    out: dict[int | None, dict[tuple[int, int], float]] = {}
    for (cid, ym), total in gastos.groupby(["cid", "ym"], dropna=False)["amount"].sum().items():
        clave = None if cid is None or pd.isna(cid) else int(cid)
        out.setdefault(clave, {})[ym] = -float(total)
    return out


def _ingresos_por_mes(df: pd.DataFrame) -> dict[tuple[int, int], float]:
    ingresos = df.loc[(df["amount"] > 0) & (df["budget_group"] == BudgetGroup.INGRESO.value)]
    serie = ingresos.groupby([ingresos["date"].dt.year, ingresos["date"].dt.month])["amount"].sum()
    return {(int(y), int(m)): float(v) for (y, m), v in serie.items()}


class _Prevision:
    """Previsión de gasto por categoría y mes futuro (ver docstring del módulo)."""

    def __init__(self, db: Session, gasto: dict, categorias: dict[int, Category], hoy: date):
        self.gasto = gasto
        self.categorias = categorias
        self.cerrados6 = _meses_cerrados(hoy, MESES_MEDIA_VARIABLE)
        self.cerrados3 = _meses_cerrados(hoy, MESES_MEDIANA_RECURRENTE)
        self.presupuestos: dict[tuple[int, int, int], float] = {
            (b.category_id, b.year, b.month): float(b.monthly_limit)
            for b in db.query(Budget).filter(Budget.active.is_(True), Budget.year >= hoy.year).all()
        }

    def _real(self, cid: int | None, ym: tuple[int, int]) -> float:
        return self.gasto.get(cid, {}).get(ym, 0.0)

    def base(self, cid: int | None) -> float:
        cat = self.categorias.get(cid) if cid is not None else None
        if cat is not None and cat.recurrente:
            return statistics.median(self._real(cid, ym) for ym in self.cerrados3)
        # Sin el mes más alto: una compra extraordinaria (un ordenador, un viaje) no se
        # repite cada mes y, metida en la media, inflaría todos los meses que quedan.
        importes = sorted(self._real(cid, ym) for ym in self.cerrados6)[:-1]
        return sum(importes) / len(importes)

    def mes(self, cid: int | None, year: int, month: int) -> dict:
        """{"importe", "origen", "año_pasado" (solo si el presupuesto se queda corto)}."""
        cat = self.categorias.get(cid) if cid is not None else None
        presupuesto = self.presupuestos.get((cid, year, month)) if cid is not None else None
        if cat is not None and cat.anual:
            año_pasado = self._real(cid, (year - 1, month))
            importe = max(presupuesto or 0.0, año_pasado, self.base(cid))
            corto = presupuesto is not None and año_pasado > presupuesto + 0.5
            return {
                "importe": importe,
                "origen": "presupuesto" if presupuesto is not None and importe == presupuesto else "año pasado",
                "año_pasado": año_pasado if corto else None,
            }
        if presupuesto is not None:
            return {"importe": presupuesto, "origen": "presupuesto", "año_pasado": None}
        return {"importe": self.base(cid), "origen": "media", "año_pasado": None}


def _celda(real: float, prevision: dict | None, estado: str) -> dict:
    if estado == "cerrado":
        return {"importe": real, "origen": "real", "aviso": None}
    importe = prevision["importe"]
    if estado == "en_curso":
        importe = max(real, importe)
    aviso = None
    if prevision.get("año_pasado") is not None:
        aviso = f"Presupuesto corto: el mismo mes del año pasado fueron {prevision['año_pasado']:.2f} €"
    return {"importe": importe, "origen": prevision["origen"], "aviso": aviso, "real": real}


def _estado_mes(year: int, month: int, hoy: date) -> str:
    if (year, month) < (hoy.year, hoy.month):
        return "cerrado"
    if (year, month) == (hoy.year, hoy.month):
        return "en_curso"
    return "previsto"


def _ingresos_previstos(db: Session, hoy: date) -> float:
    """Ingresos regulares (nómina, alquiler), igual que budget_service.balance_mes."""
    meses = _meses_cerrados(hoy, budget_service.MESES_INGRESOS)
    total = 0.0
    for por_mes in budget_service._ingresos_por_mes(db, meses).values():
        if budget_service._es_regular(por_mes, meses):
            total += statistics.median(por_mes[ym] for ym in meses)
    return total


def hucha_anual(db: Session, hoy: date | None = None) -> dict:
    """Pagos anuales de los próximos 12 meses y cuánto apartar al mes para llegar a todos.

    `aportacion` es la cantidad constante mínima que, empezando hoy desde cero, cubre cada
    pago a tiempo: max sobre k de (pagos acumulados hasta el mes k) / k. Es mayor que el
    simple total/12 cuando un recibo grande cae pronto.
    """
    hoy = hoy or date.today()
    categorias = load_categories(db)
    df = load_transactions_df(db)
    gasto = _gasto_por_mes(df) if not df.empty else {}
    prevision = _Prevision(db, gasto, categorias, hoy)
    anuales = [c for c in categorias.values() if c.anual and c.parent_id is not None]

    meses, acumulado, aportacion = [], 0.0, 0.0
    ym = (hoy.year, hoy.month)
    for k in range(1, MESES_HUCHA + 1):
        ym = _mes_siguiente(*ym)
        conceptos = []
        for cat in anuales:
            # Solo lo que excede de un mes normal (la comunidad de 30 €/mes ya va en el
            # presupuesto de cada mes): eso es lo que hay que tener ahorrado aparte.
            importe = prevision.mes(cat.id, *ym)["importe"] - prevision.base(cat.id)
            if importe >= 1:
                conceptos.append({"etiqueta": f"{cat.parent.name} · {cat.name}", "importe": importe})
        total_mes = sum(c["importe"] for c in conceptos)
        acumulado += total_mes
        aportacion = max(aportacion, acumulado / k)
        meses.append({"year": ym[0], "month": ym[1], "nombre": f"{MONTHS_ES[ym[1]]} {ym[0]}",
                      "total": total_mes, "conceptos": conceptos})

    return {
        "meses": meses,
        "total": acumulado,
        "media_mensual": acumulado / MESES_HUCHA,
        "aportacion": aportacion,
    }


def hucha_grandes(db: Session, hoy: date | None = None) -> dict:
    """Cuánto apartar al mes para los gastos gordos no mensuales (vacaciones, un portátil).

    No hay una marca de categoría para esto: sale del histórico. En cada categoría DESEO
    variable, un mes es un "pico" si gasta al menos UMBRAL_PICO por encima de su mediana
    de los últimos MESES_GRANDES meses cerrados; lo que excede de la mediana es lo que no
    cabe en un mes normal. `aportacion` reparte esos excesos del último año en doce partes:
    supone que el año que viene se parecerá a este.
    """
    hoy = hoy or date.today()
    categorias = load_categories(db)
    df = load_transactions_df(db)
    gasto = _gasto_por_mes(df) if not df.empty else {}
    meses = _meses_cerrados(hoy, MESES_GRANDES)

    picos = []
    for cat in categorias.values():
        if cat.parent_id is None or cat.budget_group != BudgetGroup.DESEO or cat.recurrente or cat.anual:
            continue
        por_mes = gasto.get(cat.id, {})
        mediana = statistics.median(por_mes.get(ym, 0.0) for ym in meses)
        for ym in meses:
            exceso = por_mes.get(ym, 0.0) - mediana
            if exceso >= UMBRAL_PICO:
                picos.append({
                    "etiqueta": category_label(cat.id, categorias),
                    "nombre": f"{MONTHS_ES[ym[1]]} {ym[0]}",
                    "ym": ym,
                    "importe": exceso,
                })
    picos.sort(key=lambda p: -p["importe"])
    total = sum(p["importe"] for p in picos)
    return {
        "picos": picos, "total": total, "aportacion": total / MESES_GRANDES,
        "meses": MESES_GRANDES, "umbral": UMBRAL_PICO,
    }


def resumen_anual(db: Session, year: int, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    categorias = load_categories(db)
    df = load_transactions_df(db)
    gasto = _gasto_por_mes(df) if not df.empty else {}
    ingresos_reales = _ingresos_por_mes(df) if not df.empty else {}
    prevision = _Prevision(db, gasto, categorias, hoy)
    estados = {m: _estado_mes(year, m, hoy) for m in range(1, 13)}

    def fila(cid: int | None, etiqueta: str) -> dict | None:
        celdas = []
        for m in range(1, 13):
            real = gasto.get(cid, {}).get((year, m), 0.0)
            prev = prevision.mes(cid, year, m) if estados[m] != "cerrado" else None
            celdas.append(_celda(real, prev, estados[m]))
        total = sum(c["importe"] for c in celdas)
        if total < 0.5:
            return None
        return {"etiqueta": etiqueta, "celdas": celdas, "total": total}

    fijos, variables = [], []
    for cat in sorted(categorias.values(), key=lambda c: (c.parent.name if c.parent else "", c.name)):
        if cat.parent_id is None or cat.is_transfer_category or cat.budget_group not in GRUPOS_GASTO:
            continue
        f = fila(cat.id, f"{cat.parent.name} · {cat.name}")
        if f is None:
            continue
        f["anual"] = cat.anual
        (fijos if cat.recurrente else variables).append(f)
    sin_clasificar = fila(None, "Sin clasificar")
    if sin_clasificar:
        sin_clasificar["anual"] = False
        variables.append(sin_clasificar)

    def suma(filas: list[dict]) -> list[float]:
        return [sum(f["celdas"][i]["importe"] for f in filas) for i in range(12)]

    total_fijos, total_variables = suma(fijos), suma(variables)
    total_gastos = [a + b for a, b in zip(total_fijos, total_variables)]

    ids_ahorro = [c.id for c in categorias.values() if c.budget_group == BudgetGroup.AHORRO]
    ingreso_previsto = _ingresos_previstos(db, hoy)
    inversion, ingresos = [], []
    for m in range(1, 13):
        invertido = sum(gasto.get(cid, {}).get((year, m), 0.0) for cid in ids_ahorro)
        ingresado = ingresos_reales.get((year, m), 0.0)
        if estados[m] != "cerrado":
            invertido = max(invertido, budget_service.inversion_esperada(db, year, m))
            ingresado = max(ingresado, ingreso_previsto)
        inversion.append(invertido)
        ingresos.append(ingresado)

    resultado = [i - g - v for i, g, v in zip(ingresos, total_gastos, inversion)]
    acumulado, corrido = [], 0.0
    for r in resultado:
        corrido += r
        acumulado.append(corrido)

    cerrados = [i for i in range(12) if estados[i + 1] == "cerrado"]
    gasto_año = sum(total_gastos)
    media = gasto_año / 12
    mes_max = max(range(12), key=lambda i: total_gastos[i])

    return {
        "year": year,
        "meses": [{"numero": m, "nombre": MONTHS_ES[m][:3], "estado": estados[m]} for m in range(1, 13)],
        "fijos": fijos,
        "variables": variables,
        "total_fijos": total_fijos,
        "total_variables": total_variables,
        "total_gastos": total_gastos,
        "inversion": inversion,
        "ingresos": ingresos,
        "resultado": resultado,
        "acumulado": acumulado,
        "gasto_año": gasto_año,
        "gasto_real_hasta_hoy": sum(total_gastos[i] for i in cerrados),
        "ingresos_año": sum(ingresos),
        "inversion_año": sum(inversion),
        "resultado_año": sum(resultado),
        "media_mensual": media,
        "mes_max": {"nombre": MONTHS_ES[mes_max + 1], "importe": total_gastos[mes_max]},
        "avisos": sum(1 for f in fijos + variables for c in f["celdas"] if c["aviso"]),
        "ingreso_previsto": ingreso_previsto,
        # Meses cerrados con menos de la mitad de los ingresos habituales: casi siempre es
        # que falta el extracto de Mediolanum (donde entra la nómina), no que no se cobrara.
        "ingresos_incompletos": [
            MONTHS_ES[i + 1] for i in cerrados if ingresos[i] < 0.5 * ingreso_previsto
        ],
    }
