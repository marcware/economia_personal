"""Presupuestos mensuales: alta/edición por mes, copia entre meses y el cálculo de
gasto-real-vs-límite.

Es la única fuente de esa aritmética: la consumen el router /presupuestos, el aviso
budget_alerts del coach y scripts/informe_mensual.py. Antes estaba duplicada en el
router y en el advisor, con entradas ligeramente distintas.
"""

from datetime import date

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.advisor.data import load_transactions_df
from app.models import Budget, BudgetGroup, Category, FinancialGoal, GoalType, Transaction
from app.services.dashboard_service import MONTHS_ES, available_months

# A partir de este ratio el presupuesto se marca como "cerca del límite".
UMBRAL_AVISO = 0.9

# Cuántos meses futuros se pueden presupuestar por adelantado.
MESES_FUTUROS_SELECCIONABLES = 3


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
    """Gasto del mes por categoría hoja, en euros positivos. Excluye traspasos."""
    df = _month_df(db, year, month, month_df)
    if df.empty:
        return {}
    gastos = df.loc[df["amount"] < 0]
    if gastos.empty:
        return {}
    serie = -gastos.groupby("category_id")["amount"].sum()
    return {int(cid): float(importe) for cid, importe in serie.items() if pd.notna(cid)}


def _estado(ratio: float) -> str:
    """Estado de un presupuesto. Los nombres coinciden con las clases CSS de .progress-fill."""
    if ratio > 100:
        return "over"
    if ratio >= UMBRAL_AVISO * 100:
        return "near"
    return "ok"


def budget_rows(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> list[dict]:
    """Una fila por presupuesto activo del mes, con su gasto real y su estado.

    Orden: primero los fijos (recurrentes, hay que pagarlos sí o sí), después los
    variables (donde tiene sentido intentar recortar); dentro de cada grupo, alfabético
    — así siempre se sabe dónde buscar una categoría concreta.
    """
    gastos = month_expense_by_category(db, year, month, month_df)
    budgets = db.query(Budget).filter_by(active=True, year=year, month=month).all()

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
            "gasto": gasto,
            "limite": limite,
            "restante": limite - gasto,
            "ratio": min(ratio, 999),
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
    trailing_inicio = date(hoy.year - 1, hoy.month, hoy.day)
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


def budget_summary(
    db: Session, year: int, month: int, month_df: pd.DataFrame | None = None
) -> dict:
    """Resumen del mes: filas presupuestadas, totales y categorías con gasto sin presupuestar."""
    df = _month_df(db, year, month, month_df)
    filas = budget_rows(db, year, month, df)
    gastos = month_expense_by_category(db, year, month, df)

    presupuestadas = {f["budget"].category_id for f in filas}
    sin_presupuesto = []
    for cid, gasto in sorted(gastos.items(), key=lambda kv: -kv[1]):
        if cid in presupuestadas:
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
        "inversion_esperada": (inv := inversion_esperada(db, year, month)),
        "total_real_mes": totales["total_limite"] + inv,
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
    db: Session, category_id: int, year: int, month: int, monthly_limit: float
) -> Budget:
    """Crea o actualiza el presupuesto de una categoría para un mes. Reactiva si estaba quitado."""
    existing = db.query(Budget).filter_by(category_id=category_id, year=year, month=month).one_or_none()
    if existing is not None:
        existing.monthly_limit = monthly_limit
        existing.active = True
        budget = existing
    else:
        budget = Budget(category_id=category_id, year=year, month=month, monthly_limit=monthly_limit)
        db.add(budget)
    db.commit()
    return budget


def deactivate_budget(db: Session, budget_id: int) -> None:
    budget = db.get(Budget, budget_id)
    if budget is not None:
        budget.active = False
        db.commit()


def copy_month(
    db: Session,
    origen: tuple[int, int],
    destino: tuple[int, int],
    sobrescribir: bool = False,
) -> int:
    """Copia los presupuestos activos de un mes a otro. Devuelve cuántos ha escrito."""
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
        upsert_budget(db, b.category_id, destino_year, destino_month, float(b.monthly_limit))
        copiados += 1
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
    trailing_inicio = date(hoy.year - 1, hoy.month, hoy.day)

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
