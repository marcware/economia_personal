"""Lo que pide atención hoy, para la portada: una lista corta de enlaces, no un informe.

Solo cuenta y enlaza: la aritmética es de budget_service y goal_service.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import BankConnection, Transaction
from app.services import budget_service, goal_service
from app.formato import eur

# Los movimientos sin clasificar más viejos que esto ya no son tarea del día.
DIAS_SIN_CLASIFICAR = 60
# Antelación con la que se avisa de que caduca el permiso del banco.
DIAS_AVISO_PERMISO = 14


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def pendientes(db: Session, hoy: date | None = None) -> list[dict]:
    """Filas {"texto", "url", "severidad"} (severidad = la de los consejos: danger/warning/info)."""
    hoy = hoy or date.today()
    year, month = hoy.year, hoy.month
    filas = []

    superados = [f for f in budget_service.budget_rows(db, year, month) if f["estado"] == "over" and f["limite"] > 0]
    if superados:
        exceso = sum(f["gasto"] - f["limite"] for f in superados)
        filas.append({
            "texto": f"{_plural(len(superados), 'presupuesto superado', 'presupuestos superados')} "
                     f"(+{eur(exceso)} sobre lo previsto)",
            "url": f"/presupuestos?year={year}&month={month}",
            "severidad": "danger",
        })

    en_riesgo = [h for h in goal_service.goal_rows(db, year, month) if h["estado"] in ("riesgo", "incumplido")]
    if en_riesgo:
        filas.append({
            "texto": f"{_plural(len(en_riesgo), 'hito en riesgo', 'hitos en riesgo')}: "
                     + ", ".join(h["titulo"] for h in en_riesgo),
            "url": f"/presupuestos?year={year}&month={month}",
            "severidad": "warning",
        })

    sin_clasificar = (
        db.query(Transaction)
        .filter(
            Transaction.category_id.is_(None),
            Transaction.is_transfer.is_(False),
            Transaction.date >= hoy - timedelta(days=DIAS_SIN_CLASIFICAR),
        )
        .count()
    )
    if sin_clasificar:
        filas.append({
            "texto": f"{_plural(sin_clasificar, 'movimiento sin clasificar', 'movimientos sin clasificar')}",
            "url": "/movimientos?categoria=sin_clasificar",
            "severidad": "info",
        })

    # Del permiso solo importa el más reciente de cada banco: los anteriores ya están sustituidos.
    vigentes: dict[str, BankConnection] = {}
    for c in db.query(BankConnection).order_by(BankConnection.created_at).all():
        vigentes[c.aspsp_name] = c
    for c in vigentes.values():
        if c.consent_valid_until is None:
            continue
        dias = (c.consent_valid_until.date() - hoy).days
        if dias < 0:
            texto, severidad = f"El permiso de {c.aspsp_name} ha caducado: vuelve a conectarlo", "danger"
        elif dias <= DIAS_AVISO_PERMISO:
            texto, severidad = f"El permiso de {c.aspsp_name} caduca en {_plural(dias, 'día', 'días')}", "warning"
        else:
            continue
        filas.append({"texto": texto, "url": "/conexiones", "severidad": severidad})

    return filas
