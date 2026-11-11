"""Plan de pensiones de ING leído de su web (ing.ingdirect.es), sin mirar la cuenta.

La conexión bancaria (Enable Banking) solo da cuentas, no planes. La web de ING es una SPA
que habla JSON con su API: nada más entrar pide la posición global
(api.ing.ingdirect.es/position-keeping), donde está el plan (type PENSION) con su saldo y su
LOCAL_UUID; con ese id, /genoma_api/rest/products/<id>/movements da todas las aportaciones
con sus participaciones y el valor liquidativo. El login es del usuario (scripts/scrape_ing.py);
aquí se recoge la posición que la web ya pidió y se piden los movimientos con la misma sesión.
"""

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Aportacion, ManualAssetEntry, Posicion
from app.services import inversiones_service

PROVEEDOR = "ing"
NOMBRE = "Plan de pensiones ING"
SUSCRIPCION = "SUSC"
PENDIENTE = "pendiente valoraci"  # "Correcta. Cargada en cuenta. Pendiente valoración"


# --- Lectura del JSON (funciones puras) ---

def plan(posicion: dict) -> dict | None:
    """El plan de pensiones de la posición global: nombre, saldo, id local y apertura."""
    productos = posicion.get("products") or []
    for p in productos:
        if p.get("type") != "PENSION":
            continue
        ids = {i.get("type"): i.get("value") for i in p.get("identifiers") or []}
        return {"nombre": p.get("commercialName"), "saldo": float(p.get("balanceToShow") or 0),
                "id": ids.get("LOCAL_UUID"), "apertura": p.get("openingDate")}
    return None


def cuenta_ahorro(posicion: dict) -> float | None:
    """Saldo de la cuenta de ahorro (Cuenta Naranja), donde se guardan las huchas: no sale en
    la conexión bancaria, pero viene en la misma posición global."""
    for p in posicion.get("products") or []:
        if p.get("type") == "SAVINGS_ACCOUNT":
            return float(p.get("balanceToShow") or 0)
    return None


def _fecha(texto: str) -> date:
    return datetime.strptime(texto, "%d/%m/%Y").date()


def calcular(saldo: float, movimientos: list[dict]) -> dict:
    """Aportaciones y posición del plan. Una aportación ya cargada pero "pendiente de
    valoración" aún no ha comprado participaciones (no está en el saldo): se cuenta aparte
    como pendiente de invertir para que no parezca una pérdida."""
    aportaciones, avisos = [], []
    participaciones = coste = pendiente = 0.0
    for m in movimientos:
        importe = float(m.get("amount") or 0)
        id_ = "ing-" + hashlib.sha1(str(m.get("uuid")).encode()).hexdigest()[:24]
        fecha = _fecha(m["operationDate"])
        if m.get("tranCode") == SUSCRIPCION:
            aportaciones.append({"id": id_, "fecha": fecha, "importe": importe, "nota": m.get("description")})
            if PENDIENTE in (m.get("status") or "").lower():
                pendiente += importe
            else:
                participaciones += float(m.get("sharesNumbers") or 0)
                coste += importe
        else:  # traspaso de salida, rescate...: dinero que sale del plan
            aportaciones.append({"id": id_, "fecha": fecha, "importe": -abs(importe),
                                 "nota": f"{m.get('description')} ({m.get('tranCode')})"})
            participaciones -= float(m.get("sharesNumbers") or 0)
            avisos.append(f"{m['operationDate']} {m.get('description')} ({m.get('tranCode')}): contado como salida")
    posiciones = []
    if participaciones > 0:
        posiciones.append({"symbol": "PLAN", "nombre": None, "cantidad": participaciones,
                           "precio": saldo / participaciones, "valor": round(saldo, 2), "coste": round(coste, 2)})
    if pendiente:
        posiciones.append({"symbol": "EUR", "nombre": "Pendiente de invertir", "cantidad": pendiente,
                           "precio": 1.0, "valor": round(pendiente, 2), "coste": round(pendiente, 2)})
    return {"aportaciones": aportaciones, "posiciones": posiciones, "avisos": avisos}


# --- Guardado ---

def inversion(db: Session):
    return inversiones_service.inversion_de(db, PROVEEDOR, NOMBRE)


def guardar(db: Session, datos: dict) -> dict:
    """datos = {"plan": plan(...), "movimientos": [...]}."""
    calculo = calcular(datos["plan"]["saldo"], datos["movimientos"])
    inv = inversion(db)
    ya = {e for (e,) in db.query(Aportacion.external_id).filter_by(inversion_id=inv.id)}
    nuevas = [a for a in calculo["aportaciones"] if a["id"] not in ya]
    for a in nuevas:
        db.add(Aportacion(inversion_id=inv.id, fecha=a["fecha"], importe=Decimal(str(round(a["importe"], 2))),
                          nota=a["nota"], external_id=a["id"]))
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    for p in calculo["posiciones"]:
        db.add(Posicion(
            inversion_id=inv.id, symbol=p["symbol"], nombre=p["nombre"] or datos["plan"]["nombre"],
            cantidad=Decimal(str(round(p["cantidad"], 6))), precio_eur=Decimal(str(round(p["precio"], 6))),
            valor_eur=Decimal(str(p["valor"])), coste_eur=Decimal(str(p["coste"])),
            realizado_eur=Decimal("0"), recompensas=Decimal("0"), recorded_at=ahora,
        ))
    total = sum(p["valor"] for p in calculo["posiciones"])
    db.add(ManualAssetEntry(name=inv.nombre, value=Decimal(str(round(total, 2))), liquido=False, recorded_at=ahora))
    db.commit()
    return {"saldo": total, "aportaciones_nuevas": len(nuevas), "movimientos": len(datos["movimientos"]),
            "avisos": calculo["avisos"]}
