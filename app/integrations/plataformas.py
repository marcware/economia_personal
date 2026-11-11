"""Plataformas de inversión con API: una lista para que /conexiones, /inversiones y
scripts/sync_accounts.py las recorran igual. Para añadir una, su `client` debe tener
`configurado()` y su `sync_service` `sincronizar(db)`, `sincronizar_si_toca(db)` y
`ultima_foto(db)`."""

from sqlalchemy.orm import Session

from app.integrations.bit2me import client as bit2me_client
from app.integrations.bit2me import sync_service as bit2me_sync
from app.integrations.traderepublic import client as tr_client
from app.integrations.traderepublic import sync_service as tr_sync

PLATAFORMAS = [
    {"nombre": "Bit2Me", "url": "/inversiones/bit2me", "client": bit2me_client, "sync": bit2me_sync},
    {"nombre": "Trade Republic", "url": "/inversiones/trade-republic", "client": tr_client, "sync": tr_sync},
]


def sincronizar_todas(db: Session) -> list[dict]:
    """Sincroniza las configuradas. Un fallo en una no impide las demás."""
    filas = []
    for p in PLATAFORMAS:
        if not p["client"].configurado():
            continue
        try:
            filas.append({"nombre": p["nombre"], "url": p["url"], "resultado": p["sync"].sincronizar(db), "error": None})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            filas.append({"nombre": p["nombre"], "url": p["url"], "resultado": None, "error": str(exc)})
    return filas


def sincronizar_si_toca(db: Session) -> dict[str, str]:
    """Pone al día las que tengan la foto vieja; devuelve {nombre: error} de las que fallen."""
    errores = {}
    for p in PLATAFORMAS:
        r = p["sync"].sincronizar_si_toca(db)
        if r and r.get("error"):
            errores[p["nombre"]] = r["error"]
    return errores


def estado(db: Session) -> list[dict]:
    return [
        {"nombre": p["nombre"], "url": p["url"], "configurado": p["client"].configurado(),
         "ultima": p["sync"].ultima_foto(db)}
        for p in PLATAFORMAS
    ]
