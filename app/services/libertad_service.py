"""Camino a la libertad financiera: colchón, tasa de ahorro y cuánto falta para que las
inversiones cubran el gasto.

Sigue el orden clásico de prioridades de finanzas personales:
  1. Colchón de emergencia (MESES_COLCHON_OBJETIVO meses de gastos esenciales) en algo
     líquido, para que un imprevisto no acabe en préstamo.
  2. Deuda cara fuera (préstamos personales, que cuestan más de lo que rinde invertir).
  3. Invertir de forma automática y creciente: "págate primero".

La cifra de independencia financiera es la regla del 4 %: gasto anual x 25.

Las cifras miran hacia delante: si hay presupuesto, salen del plan (`plan_mensual`: ingresos
regulares previstos, gasto presupuestado más las huchas, inversión comprometida). Las medias
de los últimos MESES_MEDIA meses cerrados se dan al lado como lo que pasó de verdad, pero no
mandan: un préstamo ya liquidado o unas vacaciones seguirían diciendo durante medio año que
gastas más de lo que ingresas. Sin presupuesto, se usan las medias.

El colchón es el dinero líquido: los valores declarados como líquidos (el saldo de
Mediolanum) más las cuentas de ahorro sin trabajo asignado (Account.rol AHORRO).
"""

from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.advisor.data import load_transactions_df
from app.models import Account, AccountBalance, Budget, BudgetGroup, RolCuenta
from app.services import budget_service, disponible_service, huchas_service
from app.services.dashboard_service import MONTHS_ES
from app.services.net_worth_service import latest_manual_assets, latest_manual_liabilities

MESES_MEDIA = 6
MESES_COLCHON_OBJETIVO = 6  # un solo sueldo + hipoteca: el rango alto de los 3-6 habituales
MULTIPLO_FI = 25  # regla del 4 %
TASA_AHORRO_OBJETIVO = 20.0

# Rentabilidad anual por encima de la inflación, aproximada, de una cartera indexada
# global a largo plazo. Real, no nominal, porque el objetivo (gasto anual x 25) está en
# euros de hoy.
RENTABILIDAD_REAL = 0.04
MAX_AÑOS = 60


def valor_futuro(inicial: float, mensual: float, años: float, rentabilidad: float = RENTABILIDAD_REAL) -> float:
    """Valor de `inicial` más aportaciones de `mensual` €/mes tras `años`, interés compuesto mensual."""
    r = rentabilidad / 12
    n = round(años * 12)
    if r == 0:
        return inicial + mensual * n
    return inicial * (1 + r) ** n + mensual * ((1 + r) ** n - 1) / r


def años_hasta(objetivo: float, inicial: float, mensual: float) -> float | None:
    """Años hasta que la cartera llega al objetivo. None si no llega en MAX_AÑOS."""
    if inicial >= objetivo:
        return 0.0
    r = RENTABILIDAD_REAL / 12
    saldo = inicial
    for mes in range(1, MAX_AÑOS * 12 + 1):
        saldo = saldo * (1 + r) + mensual
        if saldo >= objetivo:
            return mes / 12
    return None


def medias_mensuales(db: Session, hoy: date | None = None) -> dict:
    """Ingresos, consumo (por grupo) e inversión medios de los últimos MESES_MEDIA meses cerrados.

    Ingresos = solo categorías INGRESO: un préstamo abonado en cuenta no es un ingreso.
    Consumo = todo gasto que no es ahorro/inversión ni EXCLUIDO (cancelar deuda no es gastar).
    """
    hoy = hoy or date.today()
    df = load_transactions_df(db)
    actual = pd.Period(year=hoy.year, month=hoy.month, freq="M")
    meses = pd.period_range(end=actual - 1, periods=MESES_MEDIA, freq="M")
    if df.empty:
        return {"ingresos": 0.0, "consumo": 0.0, "necesidades": 0.0, "inversion": 0.0, "meses": meses}

    df = df[df["date"].dt.to_period("M").isin(meses)]
    ingresos = df.loc[(df["amount"] > 0) & (df["budget_group"] == "INGRESO"), "amount"].sum()
    gastos = df[(df["amount"] < 0) & (df["budget_group"] != "EXCLUIDO")]
    inversion = -gastos.loc[gastos["budget_group"] == "AHORRO", "amount"].sum()
    consumo = -gastos.loc[gastos["budget_group"] != "AHORRO", "amount"].sum()
    necesidades = -gastos.loc[gastos["budget_group"] == "NECESIDAD", "amount"].sum()
    n = len(meses)
    return {
        "ingresos": float(ingresos) / n,
        "consumo": float(consumo) / n,
        "necesidades": float(necesidades) / n,
        "inversion": float(inversion) / n,
        "meses": meses,
    }


def mes_del_plan(db: Session, hoy: date | None = None) -> tuple[int, int] | None:
    """El presupuesto que mira hacia delante: el del mes siguiente al del ciclo de nómina si
    ya está hecho; si no, el del ciclo en curso. None si ninguno tiene presupuestos."""
    ciclo = disponible_service.ciclo_nomina(db, hoy)
    fin = ciclo["siguiente"] - timedelta(days=1)
    actual = (fin.year, fin.month)
    siguiente = (actual[0] + actual[1] // 12, actual[1] % 12 + 1)
    for year, month in (siguiente, actual):
        if db.query(Budget).filter_by(active=True, year=year, month=month).first():
            return year, month
    return None


def plan_mensual(db: Session, hoy: date | None = None) -> dict | None:
    """Un mes según el presupuesto: lo que entra, lo que se consume (topes de gasto más las
    huchas, que acabarán en recibos y viajes), lo esencial (NECESIDAD más la cuota de recibos
    anuales) y lo que se invierte."""
    mes = mes_del_plan(db, hoy)
    if mes is None:
        return None
    year, month = mes
    h = huchas_service.huchas(db, hoy)
    balance = budget_service.balance_mes(db, year, month, budget_service.budget_summary(db, year, month), h["cuota"])
    if balance is None:
        return None
    necesidades = sum(float(b.monthly_limit) for b in db.query(Budget).filter_by(active=True, year=year, month=month)
                      if b.category.budget_group == BudgetGroup.NECESIDAD)
    return {
        "year": year, "month": month, "nombre": f"{MONTHS_ES[month].lower()}",
        "ingresos": balance["total_ingresos"],
        "consumo": balance["gasto_presupuestado"] + h["cuota"],
        "necesidades": necesidades + h["huchas"][0]["cuota"],
        "inversion": balance["inversion"],
    }


def _ahorro_sin_asignar(db: Session) -> float:
    """Saldo de las cuentas de ahorro sin trabajo asignado: dinero líquido para imprevistos."""
    total = 0.0
    for cuenta in db.query(Account).filter(Account.rol == RolCuenta.AHORRO):
        fila = (db.query(AccountBalance).filter_by(account_id=cuenta.id)
                .order_by(AccountBalance.recorded_at.desc()).first())
        total += float(fila.balance) if fila else 0.0
    return total


def _tasa(ingresos: float, consumo: float) -> float | None:
    return (ingresos - consumo) / ingresos * 100 if ingresos > 0 else None


def _es_deuda_de_consumo(nombre: str) -> bool:
    """Las deudas se declaran a mano en /patrimonio; la hipoteca se reconoce por el nombre."""
    return "hipoteca" not in nombre.lower()


def resumen(db: Session, hoy: date | None = None) -> dict:
    medias = medias_mensuales(db, hoy)
    plan = plan_mensual(db, hoy)
    base = plan or medias
    ingresos, consumo, inversion, necesidades = base["ingresos"], base["consumo"], base["inversion"], base["necesidades"]

    activos = latest_manual_assets(db)
    colchon = sum(a["value"] for a in activos if a["liquido"]) + _ahorro_sin_asignar(db)
    # La Cuenta Naranja no es inversión: todo su saldo es de las huchas.
    invertido = sum(a["value"] for a in activos if not a["liquido"] and a["name"] != huchas_service.ACTIVO)
    deuda_consumo = [d for d in latest_manual_liabilities(db) if _es_deuda_de_consumo(d["name"])]

    meses_colchon = colchon / necesidades if necesidades > 0 else None
    objetivo_colchon = necesidades * MESES_COLCHON_OBJETIVO

    gasto_anual = consumo * 12
    numero_fi = gasto_anual * MULTIPLO_FI
    tasa_ahorro = _tasa(ingresos, consumo)

    aportacion_objetivo = ingresos * TASA_AHORRO_OBJETIVO / 100
    escenarios = []
    for etiqueta, mensual in (
        ("Con lo que invierte el plan" if plan else "Al ritmo actual", inversion),
        ("Aportando 100 € más al mes", inversion + 100),
        (f"Invirtiendo el {TASA_AHORRO_OBJETIVO:.0f} % de la nómina", max(aportacion_objetivo, inversion)),
    ):
        años = años_hasta(numero_fi, invertido, mensual)
        escenarios.append({
            "etiqueta": etiqueta,
            "mensual": mensual,
            "años": años,
            "en_10_años": valor_futuro(invertido, mensual, 10),
        })

    return {
        "meses_media": MESES_MEDIA,
        "plan": plan,
        # Lo que pasó de verdad, para comparar con el plan.
        "real": {**medias, "tasa_ahorro": _tasa(medias["ingresos"], medias["consumo"])},
        "ingresos_medios": ingresos,
        "consumo_medio": consumo,
        "necesidades_medias": necesidades,
        "inversion_media": inversion,
        "tasa_ahorro": tasa_ahorro,
        "tasa_ahorro_objetivo": TASA_AHORRO_OBJETIVO,
        "colchon": colchon,
        "meses_colchon": meses_colchon,
        "meses_colchon_objetivo": MESES_COLCHON_OBJETIVO,
        "objetivo_colchon": objetivo_colchon,
        "falta_colchon": max(objetivo_colchon - colchon, 0.0),
        "invertido": invertido,
        "deuda_consumo": deuda_consumo,
        "total_deuda_consumo": sum(d["value"] for d in deuda_consumo),
        "numero_fi": numero_fi,
        "progreso_fi": invertido / numero_fi * 100 if numero_fi > 0 else None,
        "rentabilidad_real": RENTABILIDAD_REAL * 100,
        "escenarios": escenarios,
    }
