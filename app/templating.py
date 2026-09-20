"""Instancia única de Jinja2Templates compartida por todos los routers, con globals
disponibles en cualquier plantilla (p.ej. el contador de autotraspasos pendientes en el nav)."""

from fastapi.templating import Jinja2Templates

from app.database import SessionLocal
from app.models import TransferCandidate, TransferCandidateStatus

templates = Jinja2Templates(directory="app/templates")


def _pending_transfer_candidates_count() -> int:
    db = SessionLocal()
    try:
        return db.query(TransferCandidate).filter_by(status=TransferCandidateStatus.PENDING).count()
    finally:
        db.close()


templates.env.globals["pending_transfer_candidates_count"] = _pending_transfer_candidates_count
