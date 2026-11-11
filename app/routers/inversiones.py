from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.bit2me import client as bit2me_client
from app.integrations.bit2me import sync_service as bit2me_sync
from app.models import Inversion, ManualAssetEntry
from app.services import inversiones_service
from app.templating import templates

router = APIRouter(prefix="/inversiones", tags=["inversiones"])


@router.get("", response_class=HTMLResponse)
def inversiones_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    # Bit2Me se pone al día solo si la última foto es vieja, para que el total sea actual.
    bit2me = bit2me_sync.sincronizar_si_toca(db)
    return templates.TemplateResponse(request, "inversiones.html", {
        "cartera": inversiones_service.cartera(db),
        "bit2me_error": bit2me.get("error") if bit2me else None,
    })


@router.post("/valor")
def actualizar_valor(name: str = Form(...), value: float = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    inv = db.query(Inversion).filter_by(nombre=name).first()
    if inv is None or inv.proveedor is not None:  # las de API no se editan a mano
        raise HTTPException(status_code=404, detail="Inversión no reconocida")
    db.add(ManualAssetEntry(name=name, value=value, liquido=False))
    db.commit()
    return RedirectResponse("/inversiones", status_code=302)


def _pagina_bit2me(request: Request, db: Session, resultado: dict | None) -> HTMLResponse:
    inv = bit2me_sync.inversion(db)
    db.commit()
    return templates.TemplateResponse(request, "inversiones_bit2me.html", {
        "m": inversiones_service.modulo_cripto(db, inv),
        "api": bit2me_client.configurado(),
        "resultado": resultado,
    })


@router.get("/bit2me", response_class=HTMLResponse)
def bit2me_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _pagina_bit2me(request, db, bit2me_sync.sincronizar_si_toca(db))


@router.post("/bit2me/sincronizar", response_class=HTMLResponse)
def sincronizar_bit2me(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        resultado = bit2me_sync.sincronizar(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        resultado = {"error": str(exc)}
    return _pagina_bit2me(request, db, resultado)
