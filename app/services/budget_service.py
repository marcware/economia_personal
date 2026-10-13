"""Presupuestos mensuales: alta/edición por mes, copia entre meses y el cálculo de
gasto-real-vs-límite.

Es la única fuente de esa aritmética: la consumen el router /presupuestos, el aviso
budget_alerts del coach y scripts/informe_mensual.py. Antes estaba duplicada en el
router y en el advisor, con entradas ligeramente distintas.
"""

import math
import statistics
from datetime import date

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.advisor.data import load_transactions_df
from app.models import (
    Account, Bank, Budget, BudgetGroup, Category, FinancialGoal, GoalType, Transaction,
)
from app.services.dashboard_service import MONTHS_ES, available_months

# A partir de este ratio el presupuesto se marca como "cerca del límite".
UMBRAL_AVISO = 0.9

# Cuántos meses futuros se pueden presupuestar por adelantado.
MESES_FUTUROS_SELECCIONABLES = 3

# Ajuste automático (ver ajustar_mes): ventana de meses que se mira hacia atrás, incluido
# el mes en curso, y en cuántos de ellos tiene que haber gasto para añadir un presupuesto.
# Pedir 2 meses evita que una compra puntual (un ordenador) cree un tope mensual.
VENTANA_AJUSTE_MESES = 6
# Meses cerrados de la columna "media" de /presupuestos (ver media_gasto_reciente).
MESES_MEDIA_GASTO = 6
MESES_CON_GASTO_PARA_AÑADIR = 2


def _month_df(db: Session, year: int, month: int, month_df: pd.DataFrame | None) -> pd.DataFrame:
    """Movimientos del mes, reutilizando el DataFrame que nos pasen si ya lo tienen cargado."""
    if month_df is not None:
        return month_df
    df = load_transactions_df(db)
    if df.empty:
        return df
    return df[(df["date"].dt.year == year) & (df["date"].dt.month == month)]


def month_expense_by_category(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> dict[int, float]:
    """Gasto neto del mes por categoría hoja, en euros positivos. Excluye traspasos.

    Neto = cargos menos devoluciones (ver month_refunds_by_category): si pago la gasolina
    y me devuelven 35 € por Bizum, mi gasto en gasolina es el cargo menos esos 35 €. Puede
    salir negativo cuando la devolución cae en un mes distinto al del cargo (reposto el 27
    y me lo devuelven el 5): ese mes la categoría tiene saldo a favor.
    """
    df = _month_df(db, year, month, month_df)
    if df.empty:
        return {}
    serie = -df.loc[df["amount"] < 0].groupby("category_id")["amount"].sum()
    neto = {int(cid): float(importe) for cid, importe in serie.items() if pd.notna(cid)}
    for cid, importe in month_refunds_by_category(db, year, month, df).items():
        neto[cid] = neto.get(cid, 0.0) - importe
    return neto


def _hace_un_año(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 de febrero
        return d.replace(year=d.year - 1, day=28)


# Grupos donde un movimiento positivo es una devolución que resta gasto. En AHORRO sería
# un reembolso de inversión y en INGRESO/EXCLUIDO no hay gasto que compensar.
GRUPOS_CON_DEVOLUCION = {BudgetGroup.NECESIDAD.value, BudgetGroup.DESEO.value}


def month_refunds_by_category(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> dict[int, float]:
    """Devoluciones del mes por categoría hoja: movimientos positivos clasificados en una
    categoría de gasto (alguien me devuelve su parte, un comercio abona una compra)."""
    df = _month_df(db, year, month, month_df)
    if df.empty:
        return {}
    abonos = df.loc[(df["amount"] > 0) & df["budget_group"].isin(GRUPOS_CON_DEVOLUCION)]
    serie = abonos.groupby("category_id")["amount"].sum()
    return {int(cid): float(importe) for cid, importe in serie.items() if pd.notna(cid)}


def _estado(ratio: float) -> str:
    """Estado de un presupuesto. Los nombres coinciden con las clases CSS de .progress-fill."""
    if ratio > 100:
        return "over"
    if ratio >= UMBRAL_AVISO * 100:
        return "near"
    return "ok"


def media_gasto_reciente(db: Session, hoy: date | None = None) -> dict[int, float]:
    """Gasto medio mensual por categoría en los MESES_MEDIA_GASTO meses cerrados anteriores
    a hoy (los meses sin gasto cuentan como 0). Es solo una referencia para leer el límite:
    cuánto se gasta de verdad frente a lo que se ha puesto de tope."""
    hoy = hoy or date.today()
    fin = date(hoy.year, hoy.month, 1)
    y, m = divmod(fin.year * 12 + fin.month - 1 - MESES_MEDIA_GASTO, 12)
    inicio = date(y, m + 1, 1)
    filas = (
        db.query(Transaction.category_id, func.sum(Transaction.amount))
        .filter(
            Transaction.category_id.isnot(None),
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
            Transaction.date >= inicio,
            Transaction.date < fin,
        )
        .group_by(Transaction.category_id)
        .all()
    )
    return {cid: -float(total) / MESES_MEDIA_GASTO for cid, total in filas}


def budget_rows(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> list[dict]:
    """Una fila por presupuesto activo del mes, con su gasto real y su estado.

    Orden: primero los fijos (recurrentes, hay que pagarlos sí o sí), después los
    variables (donde tiene sentido intentar recortar); dentro de cada grupo, alfabético
    — así siempre se sabe dónde buscar una categoría concreta.
    """
    gastos = month_expense_by_category(db, year, month, month_df)
    devuelto = month_refunds_by_category(db, year, month, month_df)
    budgets = db.query(Budget).filter_by(active=True, year=year, month=month).all()
    medias = media_gasto_reciente(db)

    filas = []
    for b in budgets:
        gasto = gastos.get(b.category_id, 0.0)
        limite = float(b.monthly_limit)
        ratio = (gasto / limite * 100) if limite > 0 else 0.0
        filas.append({
            "budget": b,
            "categoria": b.category,
            "etiqueta": f"{b.category.parent.name} · {b.category.name}",
            "recurrente": b.category.recurrente,
            "virtual": False,
            "gasto": gasto,
            "devuelto": devuelto.get(b.category_id, 0.0),
            "media": medias.get(b.category_id, 0.0),
            "limite": limite,
            "restante": limite - gasto,
            "ratio": max(min(ratio, 999), 0),
            "estado": _estado(ratio),
        })
    filas.sort(key=lambda f: (not f["recurrente"], f["etiqueta"]))
    return filas


def _subtotales(filas: list[dict]) -> dict:
    limite = sum(f["limite"] for f in filas)
    gasto = sum(f["gasto"] for f in filas)
    return {
        "filas": filas,
        "total_limite": limite,
        "total_gasto": gasto,
        "total_restante": limite - gasto,
        "ratio_total": (gasto / limite * 100) if limite > 0 else 0.0,
    }


def inversion_esperada(db: Session, year: int, month: int) -> float:
    """Cuánto se espera que salga hacia ahorro/inversión este mes (Bit2Me, Quanloop, ING...).

    No está en el presupuesto (los AHORRO no se capan, ver budget_summary), pero sigue
    siendo dinero real que sale de la cuenta este mes — sin sumarlo aquí, el "total del
    mes" del presupuesto parece más bajo de lo que de verdad hace falta tener disponible.

    Prioridad: el objetivo del hito INVERSION_MIN de ese mes si existe (es la cifra que
    el propio usuario se ha propuesto meter); si no hay hito, la media real de los
    últimos 12 meses en categorías AHORRO, igual que gastos_anuales.
    """
    hito = (
        db.query(FinancialGoal)
        .filter_by(active=True, year=year, month=month, goal_type=GoalType.INVERSION_MIN)
        .first()
    )
    if hito is not None:
        return float(hito.target_amount)

    hoy = date.today()
    trailing_inicio = _hace_un_año(hoy)
    total = (
        db.query(func.sum(Transaction.amount))
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Category.budget_group == BudgetGroup.AHORRO,
            Transaction.amount < 0,
            Transaction.date >= trailing_inicio,
            Transaction.date <= hoy,
        )
        .scalar()
    )
    return -float(total) / 12 if total else 0.0


def _fila_inversion(db: Session, year: int, month: int, month_df: pd.DataFrame | None) -> dict | None:
    """Fila "fija" para el compromiso de inversión (Bit2Me/Quanloop/ING...).

    No es un Budget real —no tiene sentido capar la inversión, invertir más es bueno—
    pero sigue siendo dinero que sale de la cuenta todos los meses igual que la hipoteca,
    así que se muestra en Fijos para que el total del mes ya lo incluya sin tener que
    sumarlo aparte. Al no ser un Budget, no pasa por budget_alerts: meter más de lo
    esperado aquí nunca se marca como "presupuesto superado".
    """
    objetivo = inversion_esperada(db, year, month)
    if objetivo <= 0:
        return None

    df = _month_df(db, year, month, month_df)
    gastado = 0.0
    if not df.empty:
        gastado = -df.loc[(df["amount"] < 0) & (df["budget_group"] == "AHORRO"), "amount"].sum()

    hoy = date.today()
    if (year, month) > (hoy.year, hoy.month):
        estado = "pendiente"
    elif gastado >= objetivo:
        estado = "cumplido"
    elif (year, month) < (hoy.year, hoy.month):
        estado = "incumplido"
    else:
        # Mes en curso: por debajo de lo esperado a estas alturas del mes -> aviso suave,
        # nunca "over" (rojo de "te has pasado"), porque pasarse aquí es bueno.
        estado = "riesgo" if gastado < objetivo * (hoy.day / 30) else "ok"

    return {
        "budget": None,
        "categoria": None,
        "etiqueta": "Inversión · Otras inversiones",
        "recurrente": True,
        "virtual": True,
        "media": 0.0,
        "gasto": gastado,
        "limite": objetivo,
        "restante": max(objetivo - gastado, 0.0),
        "ratio": min(gastado / objetivo * 100, 999) if objetivo > 0 else 0.0,
        "estado": estado,
    }


def budget_summary(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> dict:
    """Resumen del mes: filas presupuestadas, totales y categorías con gasto sin presupuestar.

    Incluye una fila "fija" para el compromiso de inversión (ver _fila_inversion) para que
    el total del mes ya cuente con ella sin tener que sumarla aparte — es dinero real que
    sale de la cuenta todos los meses, aunque no sea un Budget con tope.
    """
    df = _month_df(db, year, month, month_df)
    filas = budget_rows(db, year, month, df)
    fila_inversion = _fila_inversion(db, year, month, df)
    if fila_inversion is not None:
        filas = sorted([*filas, fila_inversion], key=lambda f: (not f["recurrente"], f["etiqueta"]))
    gastos = month_expense_by_category(db, year, month, df)
    devuelto = month_refunds_by_category(db, year, month, df)

    presupuestadas = {f["budget"].category_id for f in filas if f["budget"] is not None}
    sin_presupuesto = []
    for cid, gasto in sorted(gastos.items(), key=lambda kv: -kv[1]):
        if cid in presupuestadas or gasto <= 0:
            continue
        categoria = db.get(Category, cid)
        if categoria is None or categoria.is_transfer_category:
            continue
        if categoria.budget_group == BudgetGroup.AHORRO:
            # Un presupuesto es un tope máximo ("Límite mensual"); gastar más en ahorro
            # o inversión es bueno, no algo que capar. Ese objetivo se fija como hito
            # (INVERSION_MIN/AHORRO_MIN), no como presupuesto.
            continue
        sin_presupuesto.append({
            "categoria": categoria,
            "etiqueta": f"{categoria.parent.name} · {categoria.name}" if categoria.parent else categoria.name,
            "recurrente": categoria.recurrente,
            "gasto": gasto,
            "devuelto": devuelto.get(cid, 0.0),
        })
    sin_presupuesto.sort(key=lambda f: (not f["recurrente"], -f["gasto"]))

    fijos = _subtotales([f for f in filas if f["recurrente"]])
    variables = _subtotales([f for f in filas if not f["recurrente"]])
    totales = _subtotales(filas)  # total_limite/total_gasto/total_restante/ratio_total globales

    return {
        "year": year,
        "month": month,
        "month_name": MONTHS_ES[month],
        "filas": filas,
        "fijos": fijos,
        "variables": variables,
        "total_limite": totales["total_limite"],
        "total_gasto": totales["total_gasto"],
        "total_restante": totales["total_restante"],
        "ratio_total": totales["ratio_total"],
        "sin_presupuesto": sin_presupuesto,
        "sin_presupuesto_fijos": [f for f in sin_presupuesto if f["recurrente"]],
        "sin_presupuesto_variables": [f for f in sin_presupuesto if not f["recurrente"]],
    }



# Balance del mes (ver balance_mes): meses naturales cerrados que se miran para prever los
# ingresos, y cuánto puede oscilar un ingreso entre esos meses para contar como regular.
MESES_INGRESOS = 3
ESTABILIDAD_INGRESO = 0.8


def _ingresos_por_mes(
    db: Session, meses: list[tuple[int, int]], solo_mediolanum: bool = False
) -> dict[int, dict[tuple[int, int], float]]:
    """Ingresos (sin traspasos) por categoría INGRESO y mes natural."""
    ym = func.strftime("%Y-%m", Transaction.date)
    q = (
        db.query(Transaction.category_id, ym, func.sum(Transaction.amount))
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Category.budget_group == BudgetGroup.INGRESO,
            Transaction.amount > 0,
            Transaction.is_transfer.is_(False),
            ym.in_([f"{y}-{m:02d}" for y, m in meses]),
        )
    )
    if solo_mediolanum:
        q = q.join(Account, Account.id == Transaction.account_id).filter(Account.bank == Bank.MEDIOLANUM)
    out: dict[int, dict[tuple[int, int], float]] = {}
    for cid, clave, total in q.group_by(Transaction.category_id, ym).all():
        y, m = clave.split("-")
        out.setdefault(cid, {})[(int(y), int(m))] = float(total)
    return out


def _es_regular(por_mes: dict[tuple[int, int], float], meses: list[tuple[int, int]]) -> bool:
    """Entra todos los meses y con un importe parecido (nómina, alquiler; no los Bizum)."""
    importes = [por_mes.get(ym, 0.0) for ym in meses]
    return min(importes) > 0 and min(importes) >= ESTABILIDAD_INGRESO * max(importes)


def _meses_ingresos(year: int, month: int) -> list[tuple[int, int]]:
    """Los MESES_INGRESOS meses cerrados anteriores al mes dado (o a hoy, si es futuro)."""
    hoy = date.today()
    referencia = min((year, month), (hoy.year, hoy.month))
    anterior = (referencia[0] - 1, 12) if referencia[1] == 1 else (referencia[0], referencia[1] - 1)
    return _meses_atras(date(*anterior, 1), MESES_INGRESOS)


def ingresos_base(db: Session, year: int, month: int, ingresos_reales: float) -> float:
    """Ingresos contra los que medir el mes (hitos de ahorro, regla 50/30/20).

    La nómina entra hacia el 27, así que hasta entonces los ingresos reales del mes en
    curso son cuatro Bizum y cualquier porcentaje sale absurdo (35 € de ingresos y la
    hipoteca ya cobrada: tasa de -4.000 %). Mientras el mes está abierto se usan los
    ingresos regulares previstos si son mayores que lo que ha entrado; el número se lee
    como "así cerrarías si no gastaras nada más".
    """
    hoy = date.today()
    if (year, month) == (hoy.year, hoy.month):
        return max(ingresos_reales, ingresos_previstos(db, year, month))
    return ingresos_reales


def ingresos_previstos(db: Session, year: int, month: int) -> float:
    """Total de ingresos regulares previstos para el mes (los mismos de balance_mes)."""
    meses = _meses_ingresos(year, month)
    return sum(
        statistics.median(por_mes[ym] for ym in meses)
        for por_mes in _ingresos_por_mes(db, meses).values()
        if _es_regular(por_mes, meses)
    )


def balance_mes(db: Session, year: int, month: int, resumen: dict) -> dict | None:
    """Ingresos previstos del mes frente a lo presupuestado: cuánto margen queda y a dónde va.

    El total del presupuesto es una suma de topes de gasto; sin ponerlo al lado de lo que
    entra no dice si el plan cabe. Aquí:

        margen = ingresos regulares previstos - gasto presupuestado (fijos + variables)
        margen = inversión + colchón en Mediolanum + sin asignar

    La inversión y lo que se queda en Mediolanum no son gasto (es dinero que sigue siendo
    tuyo), así que se enseñan como destino del margen, no restando como un gasto más.

    Los ingresos previstos son la mediana de los últimos MESES_INGRESOS meses cerrados de
    cada ingreso regular (ver _es_regular). El colchón es lo que, de esos ingresos, se
    queda en Mediolanum después de traspasar a las demás cuentas.
    """
    meses = _meses_ingresos(year, month)

    ingresos = []
    for cid, por_mes in _ingresos_por_mes(db, meses).items():
        if not _es_regular(por_mes, meses):
            continue
        categoria = db.get(Category, cid)
        ingresos.append({
            "categoria": categoria,
            "importe": statistics.median(por_mes[ym] for ym in meses),
        })
    if not ingresos:
        return None
    ingresos.sort(key=lambda i: -i["importe"])
    total_ingresos = sum(i["importe"] for i in ingresos)

    # Colchón: ingresos regulares que caen en Mediolanum menos lo que sale de allí por
    # traspaso a cuentas propias, mes a mes.
    regulares = {i["categoria"].id for i in ingresos}
    entra_mediolanum = _ingresos_por_mes(db, meses, solo_mediolanum=True)
    ym = func.strftime("%Y-%m", Transaction.date)
    traspasos = dict(
        db.query(ym, func.sum(Transaction.amount))
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.bank == Bank.MEDIOLANUM,
            Transaction.is_transfer.is_(True),
            Transaction.amount < 0,
            ym.in_([f"{y}-{m:02d}" for y, m in meses]),
        )
        .group_by(ym)
        .all()
    )
    retenido = [
        sum(entra_mediolanum.get(cid, {}).get((y, m), 0.0) for cid in regulares)
        + float(traspasos.get(f"{y}-{m:02d}") or 0)
        for y, m in meses
    ]
    colchon = max(statistics.median(retenido), 0.0)

    inversion = sum(f["limite"] for f in resumen["filas"] if f["virtual"])
    gasto_presupuestado = resumen["total_limite"] - inversion
    margen = total_ingresos - gasto_presupuestado

    return {
        "meses": [f"{MONTHS_ES[m].lower()}" for _, m in meses],
        "ingresos": ingresos,
        "total_ingresos": total_ingresos,
        "fijos": resumen["fijos"]["total_limite"] - inversion,
        "variables": resumen["variables"]["total_limite"],
        "gasto_presupuestado": gasto_presupuestado,
        "margen": margen,
        "inversion": inversion,
        "colchon": colchon,
        "sin_asignar": margen - inversion - colchon,
        # Lo que llega a las cuentas del día a día y lo que sale de ellas según el plan.
        "llega_a_cuentas": total_ingresos - colchon,
        "ratio_gasto": gasto_presupuestado / total_ingresos * 100,
    }


def _siguiente_mes(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def selectable_months(db: Session) -> list[tuple[int, int]]:
    """Meses navegables en /presupuestos, más recientes primero.

    No basta con available_months(): un presupuesto se prepara *antes* de que el mes
    empiece, y esos meses todavía no tienen ningún movimiento. Por eso se añaden el mes
    en curso y los MESES_FUTUROS_SELECCIONABLES siguientes, más los meses que ya tengan
    presupuestos o hitos cargados.
    """
    meses = set(available_months(db))
    meses.update((y, m) for y, m in db.query(Budget.year, Budget.month).distinct().all())

    # Los hitos son opcionales (fase 4): si el modelo aún no existe, se ignora.
    try:
        from app.models import FinancialGoal

        meses.update((y, m) for y, m in db.query(FinancialGoal.year, FinancialGoal.month).distinct().all())
    except ImportError:
        pass

    hoy = date.today()
    cursor = (hoy.year, hoy.month)
    meses.add(cursor)
    for _ in range(MESES_FUTUROS_SELECCIONABLES):
        cursor = _siguiente_mes(*cursor)
        meses.add(cursor)

    return sorted(meses, reverse=True)


def upsert_budget(
    db: Session,
    category_id: int,
    year: int,
    month: int,
    monthly_limit: float,
    fijado: bool | None = None,
) -> Budget:
    """Crea o actualiza el presupuesto de una categoría para un mes. Reactiva si estaba quitado.

    `fijado=True` cuando es una decisión explícita del usuario sobre esa categoría (el
    formulario de /presupuestos): a partir de ahí el ajuste automático no la toca. None
    deja la marca como estaba (copias y plantillas en bloque).
    """
    existing = db.query(Budget).filter_by(category_id=category_id, year=year, month=month).one_or_none()
    if existing is not None:
        existing.monthly_limit = monthly_limit
        existing.active = True
        budget = existing
    else:
        budget = Budget(category_id=category_id, year=year, month=month, monthly_limit=monthly_limit, fijado=False)
        db.add(budget)
    if fijado is not None:
        budget.fijado = fijado
        budget.ajuste_auto = None
    db.commit()
    return budget


def deactivate_budget(db: Session, budget_id: int) -> None:
    """Quitar a mano: queda fijado, para que el ajuste automático no lo vuelva a añadir."""
    budget = db.get(Budget, budget_id)
    if budget is not None:
        budget.active = False
        budget.fijado = True
        budget.ajuste_auto = None
        db.commit()


def copy_month(
    db: Session,
    origen: tuple[int, int],
    destino: tuple[int, int],
    sobrescribir: bool = False,
) -> int:
    """Copia los presupuestos activos de un mes a otro. Devuelve cuántos ha escrito.

    Lo decidido a mano viaja con la copia: un límite fijado sigue fijado y una categoría
    quitada a mano sigue quitada, para que el ajuste automático no lo deshaga en el mes
    de destino.
    """
    origen_year, origen_month = origen
    destino_year, destino_month = destino
    if origen == destino:
        return 0

    existentes = {
        b.category_id
        for b in db.query(Budget).filter_by(year=destino_year, month=destino_month, active=True).all()
    }
    copiados = 0
    for b in db.query(Budget).filter_by(year=origen_year, month=origen_month, active=True).all():
        if b.category_id in existentes and not sobrescribir:
            continue
        upsert_budget(
            db, b.category_id, destino_year, destino_month, float(b.monthly_limit),
            fijado=True if b.fijado else None,
        )
        copiados += 1

    en_destino = {
        b.category_id for b in db.query(Budget).filter_by(year=destino_year, month=destino_month).all()
    }
    quitados = db.query(Budget).filter_by(
        year=origen_year, month=origen_month, active=False, fijado=True
    ).all()
    for b in quitados:
        if b.category_id not in en_destino:
            db.add(Budget(
                category_id=b.category_id, year=destino_year, month=destino_month,
                monthly_limit=b.monthly_limit, active=False, fijado=True,
            ))
    if quitados:
        db.commit()
    return copiados


def seed_month(
    db: Session,
    year: int,
    month: int,
    plantilla: dict[int, float],
    sobrescribir: bool = False,
) -> int:
    """Carga un {category_id: límite} en un mes. Devuelve cuántos presupuestos ha escrito."""
    existentes = {
        b.category_id for b in db.query(Budget).filter_by(year=year, month=month, active=True).all()
    }
    escritos = 0
    for category_id, limite in plantilla.items():
        if category_id in existentes and not sobrescribir:
            continue
        upsert_budget(db, category_id, year, month, float(limite))
        escritos += 1
    return escritos


def _meses_atras(hoy: date, n: int) -> list[tuple[int, int]]:
    """Los n meses naturales que acaban en el de `hoy` (incluido), del más antiguo al actual."""
    meses = []
    year, month = hoy.year, hoy.month
    for _ in range(n):
        meses.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return meses[::-1]


def _gasto_mensual_reciente(db: Session, hoy: date) -> dict[int, dict[tuple[int, int], float]]:
    """{category_id: {(año, mes): gasto}} en la ventana de ajuste, solo meses con gasto."""
    meses = _meses_atras(hoy, VENTANA_AJUSTE_MESES)
    año_mes = func.strftime("%Y-%m", Transaction.date)
    filas = (
        db.query(Transaction.category_id, año_mes, func.sum(Transaction.amount))
        .filter(
            Transaction.category_id.isnot(None),
            Transaction.amount < 0,
            Transaction.date >= date(*meses[0], 1),
            Transaction.date <= hoy,
        )
        .group_by(Transaction.category_id, año_mes)
        .all()
    )
    gasto: dict[int, dict[tuple[int, int], float]] = {}
    for category_id, ym, total in filas:
        year, month = (int(x) for x in ym.split("-"))
        gasto.setdefault(category_id, {})[(year, month)] = -float(total)
    return gasto


def _ajustable(categoria: Category) -> bool:
    """Categorías que el ajuste automático puede añadir o quitar.

    Fuera: traspasos, ahorro (no se capa, va como hito), ingresos, las ambiguas sin grupo
    y las anuales — esas caen en su mes de vencimiento y se presupuestan solo ese mes
    (plantilla de seed_presupuestos / gastos_anuales), no cada mes.
    """
    return (
        categoria.parent_id is not None
        and not categoria.is_transfer_category
        and not categoria.anual
        and categoria.budget_group in (BudgetGroup.NECESIDAD, BudgetGroup.DESEO)
    )


def _limite_sugerido(gasto_por_mes: dict[tuple[int, int], float]) -> float:
    """Media mensual en la ventana (los meses sin gasto cuentan como 0), redondeada a 5 € hacia arriba.

    Una media y no una mediana: en categorías esporádicas (el gato, ropa) la mediana es 0,
    y la media es justo lo que cuestan al mes repartidas.
    """
    media = sum(gasto_por_mes.values()) / VENTANA_AJUSTE_MESES
    return float(math.ceil(media / 5) * 5)


def ajustar_mes(db: Session, year: int, month: int, hoy: date | None = None) -> dict[str, list[Budget]]:
    """Mantiene vivo el presupuesto de un mes abierto (en curso o futuro) según el gasto reciente.

    - Añade las categorías que han tenido gasto en al menos MESES_CON_GASTO_PARA_AÑADIR de
      los últimos VENTANA_AJUSTE_MESES meses y no tienen presupuesto ese mes, con la media
      mensual como límite.
    - Quita las que no han tenido ningún gasto en toda la ventana.
    - No recalcula los importes que ya hay: solo altas y bajas. Y no toca nada que el
      usuario haya decidido a mano (Budget.fijado), ni meses pasados, ni meses que aún no
      tengan ningún presupuesto preparado (no se inventa un mes entero).

    Idempotente: se llama al abrir /presupuestos y la portada y tras sincronizar el banco.
    Las altas y bajas quedan marcadas en Budget.ajuste_auto para mostrarlas y deshacerlas.
    """
    hoy = hoy or date.today()
    cambios: dict[str, list[Budget]] = {"añadidos": [], "quitados": []}
    if (year, month) < (hoy.year, hoy.month):
        return cambios

    filas = {b.category_id: b for b in db.query(Budget).filter_by(year=year, month=month).all()}
    if not any(b.active for b in filas.values()):
        return cambios

    gasto = _gasto_mensual_reciente(db, hoy)
    for categoria in db.query(Category).filter(Category.parent_id.isnot(None)).all():
        if not _ajustable(categoria):
            continue
        budget = filas.get(categoria.id)
        if budget is not None and budget.fijado:
            continue
        meses_con_gasto = gasto.get(categoria.id, {})

        if (budget is None or not budget.active) and len(meses_con_gasto) >= MESES_CON_GASTO_PARA_AÑADIR:
            limite = _limite_sugerido(meses_con_gasto)
            if budget is None:
                budget = Budget(category_id=categoria.id, year=year, month=month, fijado=False)
                db.add(budget)
            budget.monthly_limit = limite
            budget.active = True
            budget.ajuste_auto = "añadido"
            cambios["añadidos"].append(budget)
        elif budget is not None and budget.active and not meses_con_gasto:
            budget.active = False
            budget.ajuste_auto = "quitado"
            cambios["quitados"].append(budget)

    if cambios["añadidos"] or cambios["quitados"]:
        db.commit()
    return cambios


def ajustar_meses_abiertos(db: Session, hoy: date | None = None) -> None:
    """ajustar_mes sobre el mes en curso y todos los futuros que ya tengan presupuestos."""
    hoy = hoy or date.today()
    meses = db.query(Budget.year, Budget.month).distinct().all()
    for year, month in meses:
        if (year, month) >= (hoy.year, hoy.month):
            ajustar_mes(db, year, month, hoy)


def ajustes_automaticos(db: Session, year: int, month: int) -> list[Budget]:
    """Presupuestos del mes cuya última alta o baja fue automática, para enseñarlos."""
    return (
        db.query(Budget)
        .filter(Budget.year == year, Budget.month == month, Budget.ajuste_auto.isnot(None))
        .all()
    )


def deshacer_ajuste(db: Session, budget_id: int) -> None:
    """Revierte un ajuste automático y deja la decisión fijada para que no se repita."""
    budget = db.get(Budget, budget_id)
    if budget is None or budget.ajuste_auto is None:
        return
    budget.active = budget.ajuste_auto == "quitado"
    budget.fijado = True
    budget.ajuste_auto = None
    db.commit()


# Nombre de la categoría (ver seed_rules) de lo que se paga por otros y vuelve: botes,
# recibos de la inquilina. No hay un flag propio: comparte EXCLUIDO + traspaso con
# "Traspaso entre cuentas".
CATEGORIA_DINERO_DE_PASO = "Dinero de paso (botes)"


def dinero_de_paso(db: Session, year: int, month: int) -> dict | None:
    """Lo adelantado por otros y lo devuelto en el mes, con el saldo que queda entre ambos.

    Estos movimientos están excluidos de gasto e ingreso (por eso no salen en ninguna fila
    del presupuesto); aquí solo se enseñan para poder comprobar que lo adelantado ha vuelto.
    `saldo` < 0: falta que te devuelvan; > 0: te han dado más de lo que has pagado.
    `saldo_año` es lo mismo desde enero hasta el final de este mes: lo adelantado un mes y
    devuelto al siguiente descuadra los dos meses, pero ahí se compensa.
    """
    siguiente = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    movimientos = (
        db.query(Transaction)
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Category.name == CATEGORIA_DINERO_DE_PASO,
            Transaction.date >= date(year, month, 1),
            Transaction.date < siguiente,
        )
        .order_by(Transaction.date, Transaction.id)
        .all()
    )
    saldo_año = (
        db.query(func.sum(Transaction.amount))
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Category.name == CATEGORIA_DINERO_DE_PASO,
            Transaction.date >= date(year, 1, 1),
            Transaction.date < siguiente,
        )
        .scalar()
    )
    saldo_año = round(float(saldo_año or 0), 2)
    if not movimientos and not saldo_año:
        return None
    adelantado = float(-sum(t.amount for t in movimientos if t.amount < 0))
    devuelto = float(sum(t.amount for t in movimientos if t.amount > 0))
    return {
        "movimientos": movimientos,
        "adelantado": adelantado,
        "devuelto": devuelto,
        "saldo": round(devuelto - adelantado, 2),
        "saldo_año": saldo_año,
    }


def _gasto_categoria_entre(db: Session, category_id: int, desde: date, hasta: date) -> float:
    total = (
        db.query(func.sum(Transaction.amount))
        .filter(
            Transaction.category_id == category_id,
            Transaction.amount < 0,
            Transaction.date >= desde,
            Transaction.date <= hasta,
        )
        .scalar()
    )
    return -float(total) if total else 0.0


def gastos_anuales(db: Session, year: int) -> list[dict]:
    """Categorías que caen en bloque una o dos veces al año (Category.anual=True).

    Se muestran aparte del presupuesto mensual porque en su mes de vencimiento (p.ej.
    octubre para el IBI) inflan ese mes de forma normal y esperada, no por un
    sobrecoste: verlas solo mes a mes no deja ver que es un pago anual, no una anomalía.

    "Estimado anual" sale del gasto real de los últimos 12 meses, no de un presupuesto
    fijado a mano — todavía no hay un año completo de presupuestos cargado para poder
    sumarlos. "Gastado este año" es desde el 1 de enero de `year`.
    """
    categorias = db.query(Category).filter_by(anual=True).order_by(Category.name).all()
    if not categorias:
        return []

    hoy = date.today()
    inicio_año = date(year, 1, 1)
    fin_ytd = date(year, 12, 31) if year < hoy.year else hoy
    trailing_inicio = _hace_un_año(hoy)

    if year > hoy.year:
        meses_restantes = 12
    elif year < hoy.year:
        meses_restantes = 0
    else:
        meses_restantes = 12 - hoy.month

    filas = []
    for categoria in categorias:
        gastado_año = _gasto_categoria_entre(db, categoria.id, inicio_año, fin_ytd)
        estimado_anual = _gasto_categoria_entre(db, categoria.id, trailing_inicio, hoy)
        # No tiene sentido que el estimado quede por debajo de lo que ya llevas gastado
        # este año (p.ej. si el año pasado hubo un pago extraordinario que ya no se repite).
        estimado_anual = max(estimado_anual, gastado_año)
        restante = max(estimado_anual - gastado_año, 0.0)
        filas.append({
            "categoria": categoria,
            "etiqueta": f"{categoria.parent.name} · {categoria.name}",
            "gastado_año": gastado_año,
            "estimado_anual": estimado_anual,
            "restante": restante,
            "meses_restantes": meses_restantes,
            "por_mes_restante": (restante / meses_restantes) if meses_restantes > 0 else None,
        })
    return filas
