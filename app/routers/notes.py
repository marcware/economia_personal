from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FinancialNote
from app.templating import templates

router = APIRouter(prefix="/notas", tags=["notas"])


@router.get("", response_class=HTMLResponse)
def notas_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    notas = db.query(FinancialNote).order_by(FinancialNote.created_at.desc()).all()
    return templates.TemplateResponse(request, "notes.html", {"notas": notas})


@router.post("")
def crear_nota(
    title: str = Form(...), content: str = Form(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    db.add(FinancialNote(title=title.strip(), content=content.strip()))
    db.commit()
    return RedirectResponse("/notas", status_code=302)
