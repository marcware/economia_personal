"""Quanloop leído de su web (www.quanloop.com), sin mirar la cuenta del banco.

No tiene API pública. Su web habla JSON con /int/...: el extracto completo de la cuenta está en
/int/account-statement (ingresos TOPUP, intereses INTEREST_PAYOUT, cashback, retiradas) con el
saldo final, y el reparto entre planes de riesgo y los intereses aún por cobrar solo salen en
las páginas (renderizadas en el servidor) de informes y del panel. El login es del usuario
(enlace por email + confirmación en la app, scripts/scrape_quanloop.py); aquí se interpreta lo
que la web devuelve dentro de esa sesión.

Los intereses se pagan en la propia cuenta y se reinvierten: no son dinero tuyo nuevo, son la
ganancia. Lo aportado son solo los ingresos menos las retiradas.
"""

import html as html_lib
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Aportacion, ManualAssetEntry, Posicion
from app.services import inversiones_service

BASE = "https://www.quanloop.com"
PROVEEDOR = "quanloop"
NOMBRE = "Quanloop"
INICIO_HISTORICO = date(2015, 1, 1)

INGRESO = "TOPUP"
RENDIMIENTOS = ("INTEREST", "CASHBACK", "BONUS", "REFERRAL")  # dentro del tipo: lo que Quanloop te paga
PLANES = (("LOW", "Riesgo bajo"), ("MEDIUM", "Riesgo medio"), ("HIGH", "Riesgo alto"))


# --- Lectura (funciones puras) ---

def _texto(pagina: str) -> str:
    sin_codigo = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", pagina, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", sin_codigo))).strip()


def _eur(texto: str) -> float:
    return float(texto.replace(",", ""))


def planes(pagina_informe: str) -> dict[str, float]:
    """Dinero asignado hoy a cada plan de riesgo: la primera fila (la más reciente) del
    informe de inversiones diarias, "Low risk Medium risk High risk €870 €290 €0"."""
    fila = re.search(r"Low risk Medium risk High risk €([\d,.]+) €([\d,.]+) €([\d,.]+)", _texto(pagina_informe))
    if not fila:
        return {}
    return {clave: _eur(fila.group(i + 1)) for i, (clave, _) in enumerate(PLANES)}


def por_cobrar(panel: str) -> float:
    """Intereses ya ganados que Quanloop paga el día 15 del mes siguiente ("Profit payout
    (15.11.2026) €9.15"): son tuyos pero aún no están en el saldo."""
    return round(sum(_eur(x) for x in re.findall(r"Profit payout \(\d{2}\.\d{2}\.\d{4}\) €([\d,.]+)", _texto(panel))), 2)


def calcular(extracto: dict, asignado: dict[str, float], pendiente: float = 0.0) -> dict:
    """Aportaciones, rendimientos cobrados y posición (por plan de riesgo) a partir del extracto."""
    aportaciones, avisos = [], []
    cobrado = 0.0
    for e in extracto.get("entries") or []:
        tipo, importe = e.get("type") or "", float(e.get("amount") or 0)
        fecha = date.fromisoformat(e["date"])
        id_ = f"quanloop-{e['id']}"
        if tipo == INGRESO:
            aportaciones.append({"id": id_, "fecha": fecha, "importe": importe, "nota": "Ingreso desde tu banco"})
        elif any(r in tipo for r in RENDIMIENTOS) and importe >= 0:
            cobrado += importe
        elif importe < 0:  # retirada a tu banco (u otra salida): dinero que vuelve a ti
            aportaciones.append({"id": id_, "fecha": fecha, "importe": importe, "nota": f"Retirada ({tipo})"})
            if "WITHDRAW" not in tipo:
                avisos.append(f"{e['date']} {tipo} {importe:.2f} €: contado como dinero que sale")
        else:
            cobrado += importe
            avisos.append(f"{e['date']} {tipo} {importe:.2f} €: tipo nuevo, contado como rendimiento")

    saldo = float(extracto.get("endBalance") or 0)
    posiciones = []
    for clave, nombre in PLANES:
        if asignado.get(clave):
            posiciones.append({"symbol": clave, "nombre": nombre, "valor": asignado[clave], "coste": asignado[clave], "realizado": 0.0})
    # El efectivo sin asignar es lo que queda del saldo; los intereses cobrados se apuntan
    # aquí, en la cuenta donde se pagan.
    posiciones.append({"symbol": "EUR", "nombre": "Sin asignar", "valor": round(saldo - sum(asignado.values()), 2),
                       "coste": round(saldo - sum(asignado.values()), 2), "realizado": round(cobrado, 2)})
    if pendiente:
        posiciones.append({"symbol": "PENDIENTE", "nombre": "Intereses por cobrar", "valor": pendiente, "coste": 0.0, "realizado": 0.0})
    return {"aportaciones": aportaciones, "posiciones": posiciones, "saldo": saldo, "cobrado": round(cobrado, 2),
            "pendiente": pendiente, "avisos": avisos}


# --- Guardado ---

def inversion(db: Session):
    return inversiones_service.inversion_de(db, PROVEEDOR, NOMBRE)


def guardar(db: Session, datos: dict) -> dict:
    """datos = {"extracto": JSON de /int/account-statement, "informe": HTML del informe de
    inversiones diarias, "panel": HTML del panel}."""
    calculo = calcular(datos["extracto"], planes(datos.get("informe") or ""), por_cobrar(datos.get("panel") or ""))
    inv = inversion(db)
    ya = {e for (e,) in db.query(Aportacion.external_id).filter_by(inversion_id=inv.id)}
    nuevas = [a for a in calculo["aportaciones"] if a["id"] not in ya]
    for a in nuevas:
        db.add(Aportacion(inversion_id=inv.id, fecha=a["fecha"], importe=Decimal(str(round(a["importe"], 2))),
                          nota=a["nota"], external_id=a["id"]))
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    for p in calculo["posiciones"]:
        db.add(Posicion(
            inversion_id=inv.id, symbol=p["symbol"], nombre=p["nombre"], cantidad=Decimal(str(p["valor"])),
            precio_eur=Decimal("1"), valor_eur=Decimal(str(p["valor"])), coste_eur=Decimal(str(p["coste"])),
            realizado_eur=Decimal(str(p["realizado"])), recompensas=Decimal("0"), recorded_at=ahora,
        ))
    total = round(sum(p["valor"] for p in calculo["posiciones"]), 2)
    db.add(ManualAssetEntry(name=inv.nombre, value=Decimal(str(total)), liquido=False, recorded_at=ahora))
    db.commit()
    return {"total": total, "saldo": calculo["saldo"], "cobrado": calculo["cobrado"], "pendiente": calculo["pendiente"],
            "aportaciones_nuevas": len(nuevas), "movimientos": len(datos["extracto"].get("entries") or []),
            "avisos": calculo["avisos"]}
