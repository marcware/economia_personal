"""Agregaciones mensuales (pandas) para el dashboard: ingresos, gastos, ahorro
y desglose por categoría, excluyendo siempre los traspasos entre cuentas propias."""

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Category, Transaction

MONTHS_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _load_transactions_df(db: Session) -> pd.DataFrame:
    rows = db.query(
        Transaction.date, Transaction.amount, Transaction.category_id, Transaction.is_transfer
    ).all()
    df = pd.DataFrame(rows, columns=["date", "amount", "category_id", "is_transfer"])
    if df.empty:
        return df
    df["amount"] = df["amount"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    grupos = {c.id: c.budget_group.value for c in db.query(Category).all() if c.budget_group}
    df["budget_group"] = df["category_id"].map(grupos)
    return df


def _es_ingreso(df: pd.DataFrame) -> pd.Series:
    """Ingreso = abono en una categoría INGRESO. Un positivo en otra categoría es una
    devolución, o un préstamo abonado en cuenta: no es dinero ganado."""
    return (df["amount"] > 0) & (df["budget_group"] == "INGRESO")


def available_months(db: Session) -> list[tuple[int, int]]:
    """Meses con movimientos, más recientes primero."""
    df = _load_transactions_df(db)
    if df.empty:
        return []
    periods = df["date"].dt.to_period("M").unique()
    return sorted({(p.year, p.month) for p in periods}, reverse=True)


def _category_label(category_id: int | None, categories: dict[int, Category]) -> str:
    if category_id is None:
        return "Sin clasificar"
    cat = categories.get(category_id)
    if cat is None:
        return "Sin clasificar"
    if cat.parent_id and cat.parent_id in categories:
        return f"{categories[cat.parent_id].name} · {cat.name}"
    return cat.name


def monthly_summary(db: Session, year: int, month: int) -> dict:
    df = _load_transactions_df(db)
    empty = {
        "year": year, "month": month, "month_name": MONTHS_ES[month],
        "ingresos": 0.0, "gastos": 0.0, "ahorro": 0.0, "tasa_ahorro": None,
        "otros_abonos": 0.0, "desglose_categorias": [],
    }
    if df.empty:
        return empty

    mask = (df["date"].dt.year == year) & (df["date"].dt.month == month) & (~df["is_transfer"])
    month_df = df[mask]
    if month_df.empty:
        return empty

    ingresos = float(month_df.loc[_es_ingreso(month_df), "amount"].sum())
    otros_abonos = float(month_df.loc[(month_df["amount"] > 0) & ~_es_ingreso(month_df), "amount"].sum())
    gastos = float(-month_df.loc[month_df["amount"] < 0, "amount"].sum())
    ahorro = ingresos - gastos

    categories = {c.id: c for c in db.query(Category).all()}
    gasto_df = month_df[month_df["amount"] < 0].copy()
    gasto_df["amount"] = -gasto_df["amount"]
    gasto_df["categoria"] = gasto_df["category_id"].apply(lambda cid: _category_label(cid, categories))
    desglose = gasto_df.groupby("categoria")["amount"].sum().sort_values(ascending=False)

    return {
        "year": year,
        "month": month,
        "month_name": MONTHS_ES[month],
        "ingresos": round(ingresos, 2),
        "gastos": round(gastos, 2),
        "ahorro": round(ahorro, 2),
        "otros_abonos": round(otros_abonos, 2),
        "tasa_ahorro": round(ahorro / ingresos * 100, 1) if ingresos else None,
        "desglose_categorias": [{"categoria": k, "importe": round(v, 2)} for k, v in desglose.items()],
    }


def evolution(db: Session, months: int = 12) -> list[dict]:
    """Ingresos/gastos por mes, para el gráfico de evolución."""
    df = _load_transactions_df(db)
    if df.empty:
        return []
    df = df[~df["is_transfer"]].copy()
    df["period"] = df["date"].dt.to_period("M")

    df["ingreso"] = df["amount"].where(_es_ingreso(df), 0.0)
    df["gasto"] = (-df["amount"]).where(df["amount"] < 0, 0.0)
    grouped = df.groupby("period").agg(
        ingresos=("ingreso", "sum"), gastos=("gasto", "sum")
    ).sort_index().tail(months)

    return [
        {"label": str(period), "ingresos": round(float(row.ingresos), 2), "gastos": round(float(row.gastos), 2)}
        for period, row in grouped.iterrows()
    ]
