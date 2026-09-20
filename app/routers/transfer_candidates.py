from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, TransferCandidate, TransferCandidateStatus
from app.services.category_service import assign_category
from app.templating import templates

router = APIRouter(prefix="/autotraspasos", tags=["autotraspasos"])

TRASPASO_CATEGORY_NAME = "Traspaso entre cuentas"


def _traspaso_category_id(db: Session) -> int:
    cat = db.query(Category).filter_by(name=TRASPASO_CATEGORY_NAME).one()
    return cat.id


@router.get("", response_class=HTMLResponse)
def autotraspasos_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    pendientes = (
        db.query(TransferCandidate)
        .filter_by(status=TransferCandidateStatus.PENDING)
        .order_by(TransferCandidate.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(request, "transfer_candidates.html", {"pendientes": pendientes})


@router.post("/{candidate_id}/confirmar")
def confirmar(candidate_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    candidate = db.get(TransferCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")

    category_id = _traspaso_category_id(db)
    assign_category(db, candidate.transaction_id, category_id, apply_to_similar=True)
    assign_category(db, candidate.matched_transaction_id, category_id, apply_to_similar=True)

    candidate.status = TransferCandidateStatus.CONFIRMED
    db.commit()
    return RedirectResponse("/autotraspasos", status_code=302)


@router.post("/{candidate_id}/rechazar")
def rechazar(candidate_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    candidate = db.get(TransferCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidato no encontrado")
    candidate.status = TransferCandidateStatus.REJECTED
    db.commit()
    return RedirectResponse("/autotraspasos", status_code=302)
