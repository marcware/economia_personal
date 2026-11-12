from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ManualAssetEntry, ManualLiabilityEntry
from app.services import dinero_service, huchas_service, inversiones_service, libertad_service
from app.services.net_worth_service import net_worth_summary
from app.templating import templates

router = APIRouter(prefix="/patrimonio", tags=["patrimonio"])


@router.get("", response_class=HTMLResponse)
def patrimonio_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    summary = net_worth_summary(db)
    libertad = libertad_service.resumen(db)
    dinero = dinero_service.mi_dinero(db)
    # Las inversiones se apuntan en /inversiones; aquí solo su total. Mediolanum y la Cuenta
    # Naranja son valores declarados, pero se enseñan con las cuentas, donde tienen su trabajo.
    nombres = inversiones_service.nombres(db)
    cuentas_declaradas = {dinero_service.ACTIVO_MEDIOLANUM, huchas_service.ACTIVO}
    inversiones = [a for a in summary["assets"] if a["name"] in nombres]
    otros = [a for a in summary["assets"] if a["name"] not in nombres | cuentas_declaradas]
    return templates.TemplateResponse(
        request, "net_worth.html",
        {"summary": summary, "libertad": libertad, "dinero": dinero, "otros_activos": otros,
         "total_inversiones": sum(a["value"] for a in inversiones),
         "total_otros": sum(a["value"] for a in otros)},
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
