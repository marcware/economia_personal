"""Foto de la cartera de Trade Republic con sus propios datos (nunca los del banco).

Cada sincronización:
- guarda como Aportacion cada ingreso o retirada de dinero de la cuenta (sin duplicar:
  external_id es el id del movimiento en Trade Republic). Qué es ingreso y qué retirada lo
  decide la tabla de tipos de pytr (la misma que usa para exportar a Portfolio Performance).
- añade una Posicion por activo (ISIN) con cantidad, precio actual y coste según el precio
  medio de compra que calcula el propio Trade Republic, y otra "EUR" con el efectivo;
- añade una ManualAssetEntry("Trade Republic") con el total, que es lo que suma /patrimonio.
Se lanza igual que la de Bit2Me (al abrir /inversiones o su módulo si la foto es vieja, en
/conexiones y con sync_accounts.py), pero solo con una sesión abierta: si ha caducado hay
que volver a confirmar el login en el móvil desde /inversiones/trade-republic.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pytr.event import PPEventType, tr_event_type_mapping
from sqlalchemy.orm import Session

from app.integrations.traderepublic import client
from app.models import Aportacion, Inversion, ManualAssetEntry, Posicion
from app.services import inversiones_service

PROVEEDOR = "traderepublic"
NOMBRE = "Trade Republic"
EUR = "EUR"
HORAS_FOTO = 6
ESTADOS_HECHOS = {"EXECUTED", None}  # los cancelados o pendientes no han movido dinero


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _d(x: float, decimales: int = 2) -> Decimal:
    return Decimal(str(round(x, decimales)))


def inversion(db: Session) -> Inversion:
    return inversiones_service.inversion_de(db, PROVEEDOR, NOMBRE)


def ultima_foto(db: Session) -> datetime | None:
    return inversiones_service.ultima_foto(db, inversion(db))


def calcular(datos: dict) -> dict:
    """De lo leído por client.leer() a aportaciones y posiciones (sin base de datos)."""
    aportaciones = []
    for m in datos["movimientos"]:
        tipo = tr_event_type_mapping.get((m.get("eventType") or "").upper())
        importe = (m.get("amount") or {}).get("value")
        if tipo not in (PPEventType.DEPOSIT, PPEventType.REMOVAL) or importe is None:
            continue
        if m.get("status") not in ESTADOS_HECHOS:
            continue
        signo = 1 if tipo == PPEventType.DEPOSIT else -1
        aportaciones.append({
            "id": m["id"], "fecha": datetime.fromisoformat(m["timestamp"][:10]).date(),
            "importe": signo * abs(float(importe)), "nota": m.get("title"),
        })

    posiciones, avisos = [], []
    for p in datos["posiciones"]:
        cantidad = float(p.get("netSize") or 0)
        if cantidad <= 0:
            continue
        if p.get("price") is None:
            avisos.append(f"{p.get('name') or p.get('instrumentId')}: Trade Republic no da su precio, no se cuenta")
            continue
        precio = float(p["price"])
        posiciones.append({
            "symbol": p.get("instrumentId") or p.get("isin"), "nombre": p.get("name"),
            "cantidad": cantidad, "precio": precio, "valor": round(cantidad * precio, 2),
            "coste": round(cantidad * float(p.get("averageBuyIn") or 0), 2),
        })
    efectivo = sum(float(c.get("amount") or 0) for c in datos["efectivo"] if c.get("currencyId") == EUR)
    posiciones.append({"symbol": EUR, "nombre": "Efectivo", "cantidad": efectivo, "precio": 1.0,
                       "valor": round(efectivo, 2), "coste": round(efectivo, 2)})
    return {"aportaciones": aportaciones, "posiciones": posiciones, "avisos": avisos}


def sincronizar(db: Session, datos: dict | None = None) -> dict:
    calculo = calcular(datos if datos is not None else client.leer())
    inv = inversion(db)
    ya = {e for (e,) in db.query(Aportacion.external_id).filter_by(inversion_id=inv.id)}
    nuevas = [a for a in calculo["aportaciones"] if a["id"] not in ya]
    for a in nuevas:
        db.add(Aportacion(inversion_id=inv.id, fecha=a["fecha"], importe=_d(a["importe"]),
                          nota=a["nota"], external_id=a["id"]))

    ahora = _ahora()
    for p in calculo["posiciones"]:
        db.add(Posicion(
            inversion_id=inv.id, symbol=p["symbol"], nombre=p["nombre"], cantidad=_d(p["cantidad"], 12),
            precio_eur=_d(p["precio"], 8), valor_eur=_d(p["valor"]), coste_eur=_d(p["coste"]),
            realizado_eur=Decimal("0"), recompensas=Decimal("0"), recorded_at=ahora,
        ))
    total = sum(p["valor"] for p in calculo["posiciones"])
    db.add(ManualAssetEntry(name=inv.nombre, value=_d(total), liquido=False, recorded_at=ahora))
    db.commit()
    return {"total": total, "activos": len(calculo["posiciones"]) - 1,
            "aportaciones_nuevas": len(nuevas), "avisos": calculo["avisos"]}


def sincronizar_si_toca(db: Session) -> dict | None:
    """Como la de Bit2Me: nunca lanza. Con la sesión caducada devuelve el error para que la
    página ofrezca volver a conectar."""
    if not client.configurado():
        return None
    ultima = ultima_foto(db)
    if ultima is not None and _ahora() - ultima < timedelta(hours=HORAS_FOTO):
        return None
    try:
        return sincronizar(db)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"error": str(exc), "caducada": isinstance(exc, client.TRSesionCaducada)}
