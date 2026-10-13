import pandas as pd

from app.advisor.types import Advice
from app.models import UserSettings

MARGEN_PP = 5  # puntos porcentuales de margen antes de avisar


def check(month_df: pd.DataFrame, settings: UserSettings, ingresos: float) -> list[Advice]:
    """`ingresos` es la base del mes (budget_service.ingresos_base), no se recalcula aquí."""
    if ingresos <= 0:
        return [
            Advice(
                "presupuesto_50_30_20", "info", "Sin ingresos registrados este mes",
                "No se puede calcular la regla 50/30/20 sin ingresos registrados.",
            )
        ]

    def pct(budget_group: str) -> float:
        gasto = -month_df.loc[
            (month_df["amount"] < 0) & (month_df["budget_group"] == budget_group), "amount"
        ].sum()
        return float(gasto) / ingresos * 100 if gasto else 0.0

    pct_necesidad = pct("NECESIDAD")
    pct_deseo = pct("DESEO")
    pct_ahorro = pct("AHORRO")

    needs_pct = float(settings.needs_pct)
    wants_pct = float(settings.wants_pct)
    savings_pct = float(settings.savings_pct)

    advices = []
    if pct_necesidad > needs_pct + MARGEN_PP:
        advices.append(Advice(
            "presupuesto_50_30_20", "warning", "Necesidades por encima del objetivo",
            f"Tus gastos en necesidades son el {pct_necesidad:.0f}% de tus ingresos "
            f"(objetivo: {needs_pct:.0f}%).",
        ))
    if pct_deseo > wants_pct + MARGEN_PP:
        advices.append(Advice(
            "presupuesto_50_30_20", "warning", "Deseos por encima del objetivo",
            f"Tus gastos en deseos son el {pct_deseo:.0f}% de tus ingresos "
            f"(objetivo: {wants_pct:.0f}%).",
        ))
    if pct_ahorro < savings_pct - MARGEN_PP:
        advices.append(Advice(
            "presupuesto_50_30_20", "info", "Ahorro por debajo del objetivo",
            f"Has destinado el {pct_ahorro:.0f}% de tus ingresos a ahorro/inversión "
            f"(objetivo: {savings_pct:.0f}%).",
        ))
    return advices
