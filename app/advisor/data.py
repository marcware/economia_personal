import pandas as pd
from sqlalchemy.orm import Session

from app.models import Category, Transaction


def category_label(category_id: int | None, categories: dict[int, Category]) -> str:
    cat = categories.get(category_id) if category_id is not None else None
    if cat is None:
        return "Sin clasificar"
    if cat.parent_id and cat.parent_id in categories:
        return f"{categories[cat.parent_id].name} · {cat.name}"
    return cat.name


def load_categories(db: Session) -> dict[int, Category]:
    return {c.id: c for c in db.query(Category).all()}


def load_transactions_df(db: Session) -> pd.DataFrame:
    """Todas las transacciones no-transferencia, con su categoría/subcategoría y budget_group."""
    categories = load_categories(db)

    rows = db.query(
        Transaction.date, Transaction.amount, Transaction.category_id, Transaction.is_transfer
    ).filter(Transaction.is_transfer.is_(False)).all()

    df = pd.DataFrame(rows, columns=["date", "amount", "category_id", "is_transfer"])
    if df.empty:
        df["budget_group"] = []
        df["category_label"] = []
        return df

    df["amount"] = df["amount"].astype(float)
    df["date"] = pd.to_datetime(df["date"])

    def budget_group(cid: int | None) -> str | None:
        cat = categories.get(cid)
        return cat.budget_group.value if (cat and cat.budget_group) else None

    df["budget_group"] = df["category_id"].apply(budget_group)
    df["category_label"] = df["category_id"].apply(lambda cid: category_label(cid, categories))
    return df
