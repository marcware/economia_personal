"""Gastos hormiga: compras pequeñas y prescindibles que una a una no se notan pero
sumadas sí (el "latte factor").

Un gasto hormiga es un cargo de hasta IMPORTE_MAX € en una categoría DESEO no
recurrente, o sin clasificar. Quedan fuera los fijos (una suscripción es un compromiso,
se revisa en otro sitio) y las necesidades (un súper pequeño no es un capricho).

Además del total del mes, se da el coste anual y lo que ese dinero valdría invertido,
que es lo que de verdad hace ver el tamaño del agujero.
"""

from collections import defaultdict
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.models import BudgetGroup, Category, Transaction
from app.services.libertad_service import RENTABILIDAD_REAL, valor_futuro

IMPORTE_MAX = 20.0
MESES_MEDIA = 6
TOP_COMERCIOS = 5
# Horizonte de la proyección "si lo invirtieras" (con la rentabilidad de libertad_service).
AÑOS_PROYECCION = 10


def _movimientos_hormiga(db: Session, desde: date) -> pd.DataFrame:
    deseo_variable = {
        c.id for c in db.query(Category).filter(
            Category.budget_group == BudgetGroup.DESEO, Category.recurrente.is_(False)
        ).all()
    }
    filas = (
        db.query(Transaction.date, Transaction.amount, Transaction.category_id, Transaction.description_normalized)
        .filter(
            Transaction.is_transfer.is_(False),
            Transaction.amount < 0,
            Transaction.amount >= -IMPORTE_MAX,
            Transaction.date >= desde,
        )
        .all()
    )
    filas = [f for f in filas if f.category_id is None or f.category_id in deseo_variable]
    df = pd.DataFrame(filas, columns=["date", "amount", "category_id", "descripcion"])
    if df.empty:
        return df
    df["amount"] = -df["amount"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    df["period"] = df["date"].dt.to_period("M")
    return df


def _comercio(descripcion: str) -> str:
    """Nombre de comercio legible a partir de la descripción normalizada.

    Quita el prefijo típico de ING ("pago en ...") y se queda con la primera palabra,
    que es el comercio; el resto suele ser número de tienda, ciudad o referencia
    ("CINEBIC 1 ALCOY" y "CINEBIC 2 ALCOY" son el mismo cine).
    """
    texto = descripcion.strip()
    for prefijo in ("PAGO EN ", "COMPRA EN ", "RECIBO "):
        if texto.upper().startswith(prefijo):
            texto = texto[len(prefijo):]
    return (texto.split() or ["(sin descripción)"])[0].upper()


def resumen(db: Session, year: int, month: int) -> dict:
    periodo = pd.Period(year=year, month=month, freq="M")
    inicio = (periodo - MESES_MEDIA).start_time.date()
    df = _movimientos_hormiga(db, inicio)

    vacio = {
        "importe_max": IMPORTE_MAX, "num": 0, "total": 0.0, "media_mensual": 0.0,
        "num_medio": 0.0, "anual": 0.0, "invertido": 0.0, "años": AÑOS_PROYECCION,
        "rentabilidad_real": RENTABILIDAD_REAL * 100, "comercios": [], "por_mes": [],
    }
    if df.empty:
        return vacio

    mes = df[df["period"] == periodo]
    previos = df[df["period"] < periodo]
    meses_previos = pd.period_range(end=periodo - 1, periods=MESES_MEDIA, freq="M")
    total_previos = previos.groupby("period")["amount"].sum().reindex(meses_previos, fill_value=0.0)
    num_previos = previos.groupby("period").size().reindex(meses_previos, fill_value=0)
    media = float(total_previos.mean())

    # Top comercios de los últimos 3 meses (incluido el actual): la ventana corta
    # refleja hábitos actuales, no los de hace medio año.
    recientes = df[df["period"] > periodo - 3]
    agregados: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for descripcion, importe in zip(recientes["descripcion"], recientes["amount"]):
        a = agregados[_comercio(descripcion)]
        a[0] += 1
        a[1] += importe
    comercios = sorted(
        ({"nombre": k, "num": int(v[0]), "total": v[1]} for k, v in agregados.items()),
        key=lambda c: -c["total"],
    )[:TOP_COMERCIOS]

    por_mes = [
        {"label": str(p), "total": float(total_previos.get(p, 0.0))} for p in meses_previos
    ] + [{"label": str(periodo), "total": float(mes["amount"].sum())}]

    return {
        "importe_max": IMPORTE_MAX,
        "num": int(len(mes)),
        "total": float(mes["amount"].sum()),
        "media_mensual": media,
        "num_medio": float(num_previos.mean()),
        "anual": media * 12,
        "invertido": valor_futuro(0.0, media, AÑOS_PROYECCION),
        "años": AÑOS_PROYECCION,
        "rentabilidad_real": RENTABILIDAD_REAL * 100,
        "comercios": comercios,
        "por_mes": por_mes,
    }
