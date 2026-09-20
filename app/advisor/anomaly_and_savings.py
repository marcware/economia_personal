import pandas as pd

from app.advisor.types import Advice
from app.models import UserSettings

MIN_HISTORY_MONTHS = 3
MIN_ABSOLUTE_DIFF = 10.0  # evita avisos por ruido en importes pequeños


def _monthly_category_series(df: pd.DataFrame) -> pd.DataFrame:
    gastos = df[df["amount"] < 0].copy()
    gastos["amount"] = -gastos["amount"]
    gastos["period"] = gastos["date"].dt.to_period("M")
    return gastos.groupby(["period", "category_label"])["amount"].sum().reset_index()


def check_anomalies(
    df: pd.DataFrame, year: int, month: int, settings: UserSettings, budgeted_categories: set[str]
) -> list[Advice]:
    series = _monthly_category_series(df)
    current_period = pd.Period(year=year, month=month, freq="M")

    # Gastar más de lo habitual en ahorro/inversión es bueno, no una anomalía: sin este
    # filtro, invertir más un mes dispara "Gasto inusual en Inversión..." como si fuera
    # un problema (el mismo sesgo ya corregido en los hitos y en los presupuestos).
    categorias_ahorro = set(df.loc[df["budget_group"] == "AHORRO", "category_label"].unique())

    advices = []
    for category_label, group in series.groupby("category_label"):
        if category_label in budgeted_categories or category_label == "Sin clasificar":
            continue
        if category_label in categorias_ahorro:
            continue
        history = group.loc[group["period"] < current_period, "amount"]
        if len(history) < MIN_HISTORY_MONTHS:
            continue

        media = history.mean()
        std = history.std(ddof=0) or 0.0
        current_row = group.loc[group["period"] == current_period, "amount"]
        gasto_actual = float(current_row.sum()) if not current_row.empty else 0.0

        umbral = media + float(settings.anomaly_stddev_multiplier) * std if std > 0 else media * 1.3
        if gasto_actual > umbral and (gasto_actual - media) > MIN_ABSOLUTE_DIFF:
            advices.append(Advice(
                "gasto_anomalo", "warning", f"Gasto inusual en {category_label}",
                f"Este mes llevas {gasto_actual:.2f}€ en {category_label}, frente a tu media "
                f"histórica de {media:.2f}€.",
            ))
    return advices


def check_trends(df: pd.DataFrame, year: int, month: int) -> list[Advice]:
    series = _monthly_category_series(df)
    current_period = pd.Period(year=year, month=month, freq="M")
    last_3_periods = pd.period_range(end=current_period, periods=3, freq="M")

    advices = []
    for category_label, group in series.groupby("category_label"):
        if category_label == "Sin clasificar":
            continue
        recent = group.set_index("period")["amount"].reindex(last_3_periods, fill_value=0.0)
        a, b, c = recent.tolist()
        if a > MIN_ABSOLUTE_DIFF and b > a and c > b:
            advices.append(Advice(
                "tendencia_gasto", "info", f"Tendencia al alza en {category_label}",
                f"Tu gasto en {category_label} lleva 3 meses subiendo "
                f"({a:.0f}€ → {b:.0f}€ → {c:.0f}€); si vuelves a tu nivel inicial "
                f"ahorrarías ~{c - a:.0f}€/mes.",
            ))
    return advices


def check_subscriptions(df: pd.DataFrame, year: int, month: int) -> list[Advice]:
    current_period = pd.Period(year=year, month=month, freq="M")
    mask = (
        (df["category_label"] == "Otros gastos · Suscripciones")
        & (df["amount"] < 0)
        & (df["date"].dt.to_period("M") == current_period)
    )
    total = -df.loc[mask, "amount"].sum()
    count = int(mask.sum())
    if count == 0:
        return []
    return [Advice(
        "suscripciones", "info", "Suscripciones activas",
        f"Tienes {count} cargo(s) de suscripciones este mes por un total de {total:.2f}€. "
        "Revisa si las usas todas.",
    )]
