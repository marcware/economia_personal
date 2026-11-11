import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations import plataformas
from app.integrations.bit2me import client as bit2me_client
from app.integrations.bit2me import sync_service as bit2me_sync
from app.integrations.mediolanum import pias
from app.integrations.traderepublic import client as tr_client
from app.integrations.traderepublic import sync_service as tr_sync
from app.models import Inversion, ManualAssetEntry
from app.services import inversiones_service
from app.templating import templates

router = APIRouter(prefix="/inversiones", tags=["inversiones"])


@router.get("", response_class=HTMLResponse)
def inversiones_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    # Bit2Me se pone al día solo si la última foto es vieja, para que el total sea actual.
    # Las plataformas con API se ponen al día solas si su última foto es vieja.
    errores = plataformas.sincronizar_si_toca(db)
    return templates.TemplateResponse(request, "inversiones.html", {
        "cartera": inversiones_service.cartera(db),
        "errores": errores,
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
        "m": inversiones_service.modulo(db, inv),
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


def _pagina_tr(request: Request, db: Session, resultado: dict | None = None, **extra) -> HTMLResponse:
    inv = tr_sync.inversion(db)
    db.commit()
    return templates.TemplateResponse(request, "inversiones_traderepublic.html", {
        "m": inversiones_service.modulo(db, inv),
        "configurado": tr_client.configurado(),
        "sesion": tr_client.sesion_activa(),
        "resultado": resultado,
        **extra,
    })


@router.get("/trade-republic", response_class=HTMLResponse)
def traderepublic_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _pagina_tr(request, db, tr_sync.sincronizar_si_toca(db))


@router.post("/trade-republic/sincronizar", response_class=HTMLResponse)
def traderepublic_sincronizar(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        resultado = tr_sync.sincronizar(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        resultado = {"error": str(exc)}
    return _pagina_tr(request, db, resultado)


@router.post("/trade-republic/login", response_class=HTMLResponse)
def traderepublic_login(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        login = tr_client.iniciar_login()
    except Exception as exc:  # noqa: BLE001
        return _pagina_tr(request, db, error=str(exc))
    return _pagina_tr(request, db, login=login)


@router.post("/trade-republic/confirmar", response_class=HTMLResponse)
def traderepublic_confirmar(request: Request, codigo: str = Form(""), db: Session = Depends(get_db)) -> HTMLResponse:
    try:
        tr_client.completar_login(codigo.strip() or None)
        resultado = tr_sync.sincronizar(db)  # recién conectado: primera foto ya
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return _pagina_tr(request, db, error=str(exc))
    return _pagina_tr(request, db, resultado, conectado=True)


# --- PIAS Mediolanum: sin API; se lee al entrar en su banca con scripts/scrape_mediolanum.py ---

RAIZ = Path(__file__).resolve().parent.parent.parent
REGISTRO_PIAS = RAIZ / "secrets" / "mediolanum_pias.log"


def _pagina_pias(request: Request, db: Session, **extra) -> HTMLResponse:
    inv = pias.inversion(db)
    db.commit()
    return templates.TemplateResponse(request, "inversiones_pias.html", {
        "m": inversiones_service.modulo(db, inv), **extra,
    })


@router.get("/pias", response_class=HTMLResponse)
def pias_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _pagina_pias(request, db)


@router.post("/pias/actualizar", response_class=HTMLResponse)
def pias_actualizar(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Abre el Chrome de Mediolanum en el escritorio (la app corre en este ordenador). El
    login es del usuario; el PIAS se lee solo al entrar y el navegador se cierra."""
    with REGISTRO_PIAS.open("w") as registro:
        subprocess.Popen(
            [sys.executable, str(RAIZ / "scripts" / "scrape_mediolanum.py"), "--solo-pias"],
            cwd=RAIZ, stdout=registro, stderr=subprocess.STDOUT, start_new_session=True,
        )
    return _pagina_pias(request, db, lanzado=True)
