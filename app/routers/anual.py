from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Transaction
from app.services import anual_service
from app.templating import templates

router = APIRouter(prefix="/anual", tags=["anual"])


@router.get("", response_class=HTMLResponse)
def anual_home(request: Request, year: int | None = None, db: Session = Depends(get_db)) -> HTMLResponse:
    hoy = date.today()
    primero = db.query(func.min(Transaction.date)).scalar()
    años = list(range(primero.year if primero else hoy.year, hoy.year + 2))
    if year not in años:
        year = hoy.year
    return templates.TemplateResponse(
        request,
        "anual.html",
        {
            "r": anual_service.resumen_anual(db, year, hoy),
            "hucha": anual_service.hucha_anual(db, hoy),
            "grandes": anual_service.hucha_grandes(db, hoy),
            "años": años,
        },
    )
