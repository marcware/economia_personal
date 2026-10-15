"""Instancia única de Jinja2Templates compartida por todos los routers, con globals
disponibles en cualquier plantilla (p.ej. el contador de autotraspasos pendientes en el nav)."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.database import SessionLocal
from app.formato import eur, numero
from app.models import TransferCandidate, TransferCandidateStatus

templates = Jinja2Templates(directory="app/templates")


def _pending_transfer_candidates_count() -> int:
    db = SessionLocal()
    try:
        return db.query(TransferCandidate).filter_by(status=TransferCandidateStatus.PENDING).count()
    finally:
        db.close()


def _version_estaticos() -> int:
    """Marca de versión para /static: cambia al tocar un CSS/JS, así el navegador no sirve uno viejo."""
    return int(max(f.stat().st_mtime for f in Path("app/static").rglob("*") if f.is_file()))


templates.env.filters["eur"] = eur
templates.env.filters["numero"] = numero
templates.env.globals["version_estaticos"] = _version_estaticos
templates.env.globals["pending_transfer_candidates_count"] = _pending_transfer_candidates_count
