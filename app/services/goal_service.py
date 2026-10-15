"""Hitos mensuales: objetivos explícitos ("gastar menos de X en cajeros", "invertir al
menos X") evaluados contra los movimientos reales del mes.

El estado nunca se guarda: se recalcula siempre, como los presupuestos.
"""

import calendar
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.models import BudgetGroup, Category, FinancialGoal, GoalType
from app.services import budget_service
from app.services.dashboard_service import MONTHS_ES, monthly_summary
from app.formato import numero

# "max" = cumplir es quedarse por debajo; "min" = cumplir es llegar o pasar.
GOAL_DIRECTION: dict[GoalType, str] = {
    GoalType.GASTO_MAX_CATEGORIA: "max",
    GoalType.GASTO_MAX_TOTAL: "max",
    GoalType.AHORRO_MIN: "min",
    GoalType.INVERSION_MIN: "min",
    GoalType.TASA_AHORRO_MIN: "min",
}

GOAL_UNIT: dict[GoalType, str] = {
    GoalType.GASTO_MAX_CATEGORIA: "€",
    GoalType.GASTO_MAX_TOTAL: "€",
    GoalType.AHORRO_MIN: "€",
    GoalType.INVERSION_MIN: "€",
    GoalType.TASA_AHORRO_MIN: "%",
}

GOAL_LABEL: dict[GoalType, str] = {
    GoalType.GASTO_MAX_CATEGORIA: "Gastar menos de X € en una categoría",
    GoalType.GASTO_MAX_TOTAL: "Gasto total del mes por debajo de X €",
    GoalType.AHORRO_MIN: "Ahorrar al menos X €",
    GoalType.INVERSION_MIN: "Invertir al menos X €",
    GoalType.TASA_AHORRO_MIN: "Tasa de ahorro de al menos X %",
}

# Tipos que usan category_id.
GOAL_NEEDS_CATEGORY = {GoalType.GASTO_MAX_CATEGORIA, GoalType.INVERSION_MIN}

# Tipos que dependen de los ingresos del mes: con el mes en curso se miden contra los
# ingresos previstos (ver _ingresos_base) y van bajando según se gasta, no subiendo.
GOAL_SOBRE_INGRESOS = {GoalType.AHORRO_MIN, GoalType.TASA_AHORRO_MIN}


def _inversion_del_mes(db: Session, gastos: dict[int, float], category_id: int | None) -> float:
    """Salidas hacia ahorro/inversión del mes, en euros positivos."""
    if category_id is not None:
        return gastos.get(category_id, 0.0)
    hojas_ahorro = {
        c.id for c in db.query(Category).filter(Category.budget_group == BudgetGroup.AHORRO).all()
    }
    return sum(importe for cid, importe in gastos.items() if cid in hojas_ahorro)


def _mes_en_curso(year: int, month: int) -> bool:
    hoy = date.today()
    return (year, month) == (hoy.year, hoy.month)


def _ingresos_base(db: Session, summary: dict) -> float:
    """Ingresos contra los que medir el ahorro del mes.

    La nómina entra hacia el 27, así que hasta entonces los ingresos reales del mes en
    curso son cuatro Bizum y el ahorro sale absurdo (35 € de ingresos y la hipoteca ya
    cobrada: tasa de -4.000 %). Mientras el mes está abierto se usan los ingresos
    regulares previstos (los de budget_service.balance_mes) si son mayores que lo que
    ha entrado; el número se lee como "así cerrarías si no gastaras nada más".
    """
    return budget_service.ingresos_base(db, summary["year"], summary["month"], summary["ingresos"])


def _ahorro_real(summary: dict, invertido: float, ingresos: float) -> float:
    """Dinero no destinado a consumo: lo que sobra en la cuenta + lo invertido.

    monthly_summary calcula ahorro = ingresos - gastos, y los traspasos a Quanloop,
    Fondos-Planes o Bit2Me son movimientos negativos, así que cuentan como gasto. Sin
    esta corrección, invertir más empeoraría "ahorrar más" y "gasto total" a la vez,
    aunque invertir sea justo lo que se le está pidiendo al usuario en INVERSION_MIN.
    Se le suma de vuelta lo invertido para que sea neutro: invertir ni ayuda ni
    perjudica a este número, solo mueve el dinero de "gasto" a "invertido".
    """
    return ingresos - summary["gastos"] + invertido


def _actual(db: Session, goal: FinancialGoal, summary: dict, gastos: dict[int, float]) -> float | None:
    invertido = _inversion_del_mes(db, gastos, None)

    if goal.goal_type == GoalType.GASTO_MAX_CATEGORIA:
        return gastos.get(goal.category_id, 0.0)
    if goal.goal_type == GoalType.GASTO_MAX_TOTAL:
        return summary["gastos"] - invertido
    if goal.goal_type == GoalType.AHORRO_MIN:
        return _ahorro_real(summary, invertido, _ingresos_base(db, summary))
    if goal.goal_type == GoalType.INVERSION_MIN:
        return _inversion_del_mes(db, gastos, goal.category_id)
    if goal.goal_type == GoalType.TASA_AHORRO_MIN:
        ingresos = _ingresos_base(db, summary)
        return (_ahorro_real(summary, invertido, ingresos) / ingresos * 100) if ingresos else None
    raise ValueError(f"Tipo de hito no soportado: {goal.goal_type}")


def _prorrata(year: int, month: int) -> float:
    """Qué porcentaje del mes ha transcurrido. 100 si el mes ya está cerrado."""
    hoy = date.today()
    if (year, month) < (hoy.year, hoy.month):
        return 100.0
    if (year, month) > (hoy.year, hoy.month):
        return 0.0
    return hoy.day / calendar.monthrange(year, month)[1] * 100


def _estado(ratio: float, direccion: str, year: int, month: int, sobre_ingresos: bool = False) -> str:
    hoy = date.today()
    if (year, month) > (hoy.year, hoy.month):
        return "pendiente"
    cerrado = (year, month) < (hoy.year, hoy.month)

    if direccion == "max":
        if ratio > 100:
            return "incumplido"
        if ratio >= budget_service.UMBRAL_AVISO * 100:
            return "riesgo"
        return "cumplido" if cerrado else "ok"

    if sobre_ingresos and not cerrado:
        # Parte de los ingresos previstos y baja con cada gasto: hasta el cierre no está
        # cumplido, y por debajo del objetivo ya no se recupera sin un ingreso extra.
        return "ok" if ratio >= 100 else "riesgo"
    if ratio >= 100:
        return "cumplido"
    if cerrado:
        return "incumplido"
    # En curso: se compara con lo que tocaría llevar a estas alturas del mes, para que
    # "invertir al menos 250 €" avise el día 20 y no solo el 31.
    return "riesgo" if ratio < _prorrata(year, month) else "ok"


def goal_rows(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> list[dict]:
    goals = (
        db.query(FinancialGoal)
        .filter_by(active=True, year=year, month=month)
        .order_by(FinancialGoal.id)
        .all()
    )
    if not goals:
        return []

    summary = monthly_summary(db, year, month)
    gastos = budget_service.month_expense_by_category(db, year, month, month_df)

    filas = []
    for goal in goals:
        direccion = GOAL_DIRECTION[goal.goal_type]
        unidad = GOAL_UNIT[goal.goal_type]
        objetivo = float(goal.target_amount)
        actual = _actual(db, goal, summary, gastos)

        if actual is None:
            ratio, estado = 0.0, "pendiente"
        else:
            if direccion == "max":
                ratio = (actual / objetivo * 100) if objetivo > 0 else 0.0
            else:
                ratio = (actual / objetivo * 100) if objetivo > 0 else 100.0
            estado = _estado(ratio, direccion, year, month, goal.goal_type in GOAL_SOBRE_INGRESOS)

        comparador = "≤" if direccion == "max" else "≥"
        filas.append({
            "goal": goal,
            "titulo": goal.title or _titulo_por_defecto(goal),
            "etiqueta_objetivo": f"{comparador} {numero(objetivo, 2 if objetivo % 1 else 0)} {unidad}",
            "actual": actual,
            "objetivo": objetivo,
            "unidad": unidad,
            "direccion": direccion,
            "ratio": max(min(ratio, 999), 0),
            "estado": estado,
        })
    return filas


def _titulo_por_defecto(goal: FinancialGoal) -> str:
    if goal.goal_type == GoalType.GASTO_MAX_CATEGORIA and goal.category is not None:
        return f"Gastar menos en {goal.category.name}"
    return GOAL_LABEL[goal.goal_type].replace("X €", "").replace("X %", "").strip()


def upsert_goal(
    db: Session,
    year: int,
    month: int,
    goal_type: GoalType,
    target_amount: float,
    category_id: int | None = None,
    title: str | None = None,
) -> FinancialGoal:
    """Crea o actualiza un hito. La unicidad se valida aquí, no en la tabla (ver el modelo)."""
    if goal_type == GoalType.GASTO_MAX_CATEGORIA and category_id is None:
        raise ValueError("GASTO_MAX_CATEGORIA necesita una categoría.")
    if goal_type not in GOAL_NEEDS_CATEGORY:
        category_id = None

    existing = (
        db.query(FinancialGoal)
        .filter_by(year=year, month=month, goal_type=goal_type, category_id=category_id)
        .first()
    )
    if existing is not None:
        existing.target_amount = target_amount
        existing.title = title or existing.title
        existing.active = True
        goal = existing
    else:
        goal = FinancialGoal(
            year=year, month=month, goal_type=goal_type,
            category_id=category_id, target_amount=target_amount, title=title,
        )
        db.add(goal)
    db.commit()
    return goal


def deactivate_goal(db: Session, goal_id: int) -> None:
    goal = db.get(FinancialGoal, goal_id)
    if goal is not None:
        goal.active = False
        db.commit()


def copy_goals(db: Session, origen: tuple[int, int], destino: tuple[int, int]) -> int:
    """Copia los hitos activos de un mes a otro. Devuelve cuántos ha escrito."""
    if origen == destino:
        return 0
    copiados = 0
    for g in db.query(FinancialGoal).filter_by(year=origen[0], month=origen[1], active=True).all():
        upsert_goal(
            db, destino[0], destino[1], g.goal_type, float(g.target_amount),
            category_id=g.category_id, title=g.title,
        )
        copiados += 1
    return copiados


def describe_month(year: int, month: int) -> str:
    return f"{MONTHS_ES[month]} {year}"
