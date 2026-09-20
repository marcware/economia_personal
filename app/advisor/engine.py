from sqlalchemy.orm import Session

from app.advisor import anomaly_and_savings, budget_alerts, goal_alerts, rule_50_30_20
from app.advisor.data import category_label, load_categories, load_transactions_df
from app.advisor.types import SEVERITY_ORDER, Advice
from app.models import Budget, UserSettings


def get_advice(db: Session, year: int, month: int) -> list[Advice]:
    df = load_transactions_df(db)
    if df.empty:
        return []

    settings = db.query(UserSettings).filter_by(id=1).one_or_none() or UserSettings()
    month_df = df[(df["date"].dt.year == year) & (df["date"].dt.month == month)]

    categories = load_categories(db)
    # Filtrado por mes: si no, check_anomalies silenciaría anomalías de categorías
    # presupuestadas en *otro* mes.
    active_budgets = db.query(Budget).filter_by(active=True, year=year, month=month).all()
    budgeted_categories = {category_label(b.category_id, categories) for b in active_budgets}

    advices: list[Advice] = []
    advices += rule_50_30_20.check(month_df, settings)
    advices += budget_alerts.check(db, year, month, month_df)
    advices += goal_alerts.check(db, year, month, month_df)
    advices += anomaly_and_savings.check_anomalies(df, year, month, settings, budgeted_categories)
    advices += anomaly_and_savings.check_trends(df, year, month)
    advices += anomaly_and_savings.check_subscriptions(df, year, month)

    advices.sort(key=lambda a: SEVERITY_ORDER.get(a.severity, 99))
    return advices
