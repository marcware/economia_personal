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
from app.integrations.ing import plan_pensiones
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


def _pagina_pias(request: Request, db: Session, **extra) -> HTMLResponse:
    inv = pias.inversion(db)
    db.commit()
    return templates.TemplateResponse(request, "inversiones_pias.html", {
        "m": inversiones_service.modulo(db, inv), **extra,
    })


@router.get("/pias", response_class=HTMLResponse)
def pias_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _pagina_pias(request, db)


def _lanzar(script: str, *args: str) -> None:
    """Abre en el escritorio (la app corre en este ordenador) un script que trae Chrome: el
    login es del usuario y el resto se hace solo. Su salida queda en secrets/<script>.log."""
    with (RAIZ / "secrets" / f"{Path(script).stem}.log").open("w") as registro:
        subprocess.Popen([sys.executable, str(RAIZ / "scripts" / script), *args], cwd=RAIZ,
                         stdout=registro, stderr=subprocess.STDOUT, start_new_session=True)


@router.post("/pias/actualizar", response_class=HTMLResponse)
def pias_actualizar(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _lanzar("scrape_mediolanum.py", "--solo-pias")
    return _pagina_pias(request, db, lanzado=True)


# --- Plan de pensiones ING: sin API para planes; se lee de su web con scripts/scrape_ing.py ---

@router.get("/plan-ing", response_class=HTMLResponse)
def plan_ing_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return _pagina_plan_ing(request, db)


@router.post("/plan-ing/actualizar", response_class=HTMLResponse)
def plan_ing_actualizar(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    _lanzar("scrape_ing.py")
    return _pagina_plan_ing(request, db, lanzado=True)


def _pagina_plan_ing(request: Request, db: Session, **extra) -> HTMLResponse:
    inv = plan_pensiones.inversion(db)
    db.commit()
    return templates.TemplateResponse(request, "inversiones_plan_ing.html", {
        "m": inversiones_service.modulo(db, inv), **extra,
    })
