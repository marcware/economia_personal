"""Avisos de hitos mensuales. La evaluación vive en goal_service; aquí solo se redacta.

A diferencia del resto de checks, este también emite un aviso cuando un hito se CUMPLE:
una lista de consejos que solo regaña no invita a fijarse hitos nuevos.
"""

import pandas as pd
from sqlalchemy.orm import Session

from app.advisor.types import Advice
from app.formato import eur, numero
from app.services.goal_service import goal_rows

URL_PRESUPUESTOS = "/presupuestos?year={year}&month={month}"


def _formatea(valor: float, unidad: str) -> str:
    return eur(valor) if unidad == "€" else f"{numero(valor, 1)} {unidad}"


def check(db: Session, year: int, month: int, month_df: pd.DataFrame) -> list[Advice]:
    advices = []
    url = URL_PRESUPUESTOS.format(year=year, month=month)

    for fila in goal_rows(db, year, month, month_df=month_df):
        estado, titulo = fila["estado"], fila["titulo"]
        if estado in ("pendiente", "ok"):
            continue

        actual = _formatea(fila["actual"], fila["unidad"])
        objetivo = _formatea(fila["objetivo"], fila["unidad"])

        if estado == "incumplido":
            advices.append(Advice(
                "hito", "danger", f"Hito no cumplido: {titulo}",
                f"Te quedaste en {actual} frente al objetivo de {objetivo}.", url,
            ))
        elif estado == "riesgo":
            advices.append(Advice(
                "hito", "warning", f"Hito en riesgo: {titulo}",
                f"Vas por {actual} y el objetivo es {objetivo}.", url,
            ))
        elif estado == "cumplido":
            advices.append(Advice(
                "hito", "info", f"Hito conseguido: {titulo}",
                f"Cerraste el mes en {actual} con un objetivo de {objetivo}. Bien hecho.", url,
            ))

    return advices
