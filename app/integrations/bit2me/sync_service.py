"""Foto de la cartera de Bit2Me con sus propios datos (nunca los del banco).

Cada sincronización:
- guarda como Aportacion cada entrada/salida de dinero de fuera (sin duplicar: external_id
  es el id de la operación en Bit2Me);
- añade una Posicion por moneda con cantidad, precio, valor, coste FIFO, resultado
  de ventas y recompensas (ver cartera.py);
- añade una ManualAssetEntry("Bit2Me") con el total, que es lo que suma /patrimonio.
La usan scripts/sync_accounts.py, el botón de /conexiones y /inversiones/bit2me (que
además sincroniza sola al abrirse si la última foto tiene más de HORAS_FOTO horas).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.integrations.bit2me import cartera
from app.integrations.bit2me.client import Bit2MeClient, configurado
from app.models import Aportacion, Inversion, ManualAssetEntry, Posicion
from app.services import inversiones_service

PROVEEDOR = "bit2me"
NOMBRE = "Bit2Me"
VALOR_MINIMO = 0.01  # restos de una moneda vendida: no merecen fila
HORAS_FOTO = 6


def _ahora() -> datetime:
    # En UTC, como el CURRENT_TIMESTAMP de SQLite que rellena el resto de recorded_at.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _d(x: float, decimales: int = 2) -> Decimal:
    return Decimal(str(round(x, decimales)))


def inversion(db: Session) -> Inversion:
    return inversiones_service.inversion_de(db, PROVEEDOR, NOMBRE)


def ultima_foto(db: Session) -> datetime | None:
    return inversiones_service.ultima_foto(db, inversion(db))


def sincronizar(db: Session, client: Bit2MeClient | None = None) -> dict:
    client = client or Bit2MeClient()
    saldos, avisos = client.saldos()
    operaciones = client.operaciones()
    try:
        trades = client.trades_pro()
    except httpx.HTTPError as exc:
        trades = []
        avisos.append(f"Pro: {exc} (el coste de lo comprado en Pro no se cuenta)")
    calculo = cartera.calcular(operaciones, trades, saldos)
    avisos += calculo["avisos"]

    inv = inversion(db)
    ya = {e for (e,) in db.query(Aportacion.external_id).filter_by(inversion_id=inv.id)}
    nuevas = [a for a in calculo["aportaciones"] if a["id"] not in ya]
    for a in nuevas:
        db.add(Aportacion(inversion_id=inv.id, fecha=a["fecha"], importe=_d(a["importe"]), external_id=a["id"]))

    ahora = _ahora()
    total = 0.0
    monedas = 0
    euros = saldos.get(cartera.EUR, 0.0)
    filas = [{"symbol": cartera.EUR, "cantidad": euros, "coste": euros, "realizado": 0.0, "recompensas": 0.0}]
    for p in calculo["posiciones"] + filas:
        precio = client.precio_eur(p["symbol"])
        if precio is None:
            avisos.append(f"{p['symbol']}: Bit2Me no da su precio en euros, no se cuenta")
            continue
        valor = round(p["cantidad"] * precio, 2)
        if valor < VALOR_MINIMO and abs(p["realizado"]) < VALOR_MINIMO:
            continue
        db.add(Posicion(
            inversion_id=inv.id, symbol=p["symbol"], cantidad=_d(p["cantidad"], 12), precio_eur=_d(precio, 8), valor_eur=_d(valor),
            coste_eur=_d(p["coste"]), realizado_eur=_d(p["realizado"]), recompensas=_d(p["recompensas"], 12),
            recorded_at=ahora,
        ))
        total += valor
        monedas += valor >= VALOR_MINIMO
    db.add(ManualAssetEntry(name=inv.nombre, value=_d(total), liquido=False, recorded_at=ahora))
    db.commit()
    return {"total": total, "monedas": monedas, "aportaciones_nuevas": len(nuevas), "avisos": avisos}


def sincronizar_si_toca(db: Session) -> dict | None:
    """Sincroniza si hay clave y la última foto es vieja. Nunca lanza: un fallo de Bit2Me
    no debe impedir ver la página. Devuelve el resultado, {"error": ...} o None si no tocaba."""
    if not configurado():
        return None
    ultima = ultima_foto(db)
    if ultima is not None and _ahora() - ultima < timedelta(hours=HORAS_FOTO):
        return None
    try:
        return sincronizar(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"error": str(exc)}
