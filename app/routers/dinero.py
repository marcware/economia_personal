from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import dinero_service, huchas_service
from app.templating import templates

router = APIRouter(prefix="/dinero", tags=["dinero"])


@router.get("", response_class=HTMLResponse)
def dinero_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    r = dinero_service.mi_dinero(db)
    return templates.TemplateResponse(request, "dinero.html", {"r": r, "huchas": r["huchas"]})


@router.post("/hucha-variable")
def hucha_variable(cuota: float = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    huchas_service.fijar_variable(db, max(cuota, 0.0))
    return RedirectResponse("/dinero#huchas", status_code=302)
