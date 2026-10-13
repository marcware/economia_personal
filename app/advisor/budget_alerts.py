"""Avisos de presupuesto: la aritmética vive en budget_service, aquí solo se redacta."""

import pandas as pd
from sqlalchemy.orm import Session

from app.advisor.types import Advice
from app.services.budget_service import budget_rows

URL_PRESUPUESTOS = "/presupuestos?year={year}&month={month}"


def check(db: Session, year: int, month: int, month_df: pd.DataFrame) -> list[Advice]:
    advices = []
    url = URL_PRESUPUESTOS.format(year=year, month=month)

    for fila in budget_rows(db, year, month, month_df=month_df):
        if fila["limite"] <= 0:
            continue
        nombre = fila["categoria"].name
        gasto, limite = fila["gasto"], fila["limite"]

        if fila["estado"] == "over":
            advices.append(Advice(
                "presupuesto_categoria", "danger", f"Presupuesto superado: {nombre}",
                f"Has superado el presupuesto de {nombre} en {gasto - limite:.2f}€ "
                f"({gasto:.2f}€ de {limite:.2f}€).",
                url,
            ))
        # Un fijo pagado exacto va al 100 % todos los meses: no es un aviso.
        elif fila["estado"] == "near" and not fila["recurrente"]:
            advices.append(Advice(
                "presupuesto_categoria", "warning", f"Cerca del límite: {nombre}",
                f"Vas al {fila['ratio']:.0f}% de tu presupuesto de {nombre} "
                f"({gasto:.2f}€ de {limite:.2f}€).",
                url,
            ))

    return advices
