from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ManualAssetEntry, ManualLiabilityEntry
from app.services.net_worth_service import net_worth_summary
from app.templating import templates

router = APIRouter(prefix="/patrimonio", tags=["patrimonio"])


@router.get("", response_class=HTMLResponse)
def patrimonio_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    summary = net_worth_summary(db)
    return templates.TemplateResponse(request, "net_worth.html", {"summary": summary})


@router.post("/activo")
def actualizar_activo(name: str = Form(...), value: float = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    db.add(ManualAssetEntry(name=name.strip(), value=value))
    db.commit()
    return RedirectResponse("/patrimonio", status_code=302)


@router.post("/pasivo")
def actualizar_pasivo(
    name: str = Form(...), outstanding_balance: float = Form(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    db.add(ManualLiabilityEntry(name=name.strip(), outstanding_balance=outstanding_balance))
    db.commit()
    return RedirectResponse("/patrimonio", status_code=302)
