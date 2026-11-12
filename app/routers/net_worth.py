from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ManualAssetEntry, ManualLiabilityEntry
from app.services import dinero_service, inversiones_service, libertad_service
from app.services.net_worth_service import net_worth_summary
from app.templating import templates

router = APIRouter(prefix="/patrimonio", tags=["patrimonio"])


@router.get("", response_class=HTMLResponse)
def patrimonio_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    summary = net_worth_summary(db)
    libertad = libertad_service.resumen(db)
    # Las inversiones se apuntan en /inversiones; aquí solo su total y el resto de activos.
    nombres = inversiones_service.nombres(db)
    inversiones = [a for a in summary["assets"] if a["name"] in nombres]
    otros = [a for a in summary["assets"] if a["name"] not in nombres]
    return templates.TemplateResponse(
        request, "net_worth.html",
        {"summary": summary, "libertad": libertad, "otros_activos": otros,
         "total_inversiones": sum(a["value"] for a in inversiones),
         "total_otros": sum(a["value"] for a in otros), "trabajo": dinero_service.TRABAJO},
    )


@router.post("/activo")
def actualizar_activo(
    name: str = Form(...), value: float = Form(...), liquido: bool = Form(False), db: Session = Depends(get_db)
) -> RedirectResponse:
    db.add(ManualAssetEntry(name=name.strip(), value=value, liquido=liquido))
    db.commit()
    return RedirectResponse("/patrimonio", status_code=302)


@router.post("/pasivo")
def actualizar_pasivo(
    name: str = Form(...), outstanding_balance: float = Form(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    db.add(ManualLiabilityEntry(name=name.strip(), outstanding_balance=outstanding_balance))
    db.commit()
    return RedirectResponse("/patrimonio", status_code=302)
