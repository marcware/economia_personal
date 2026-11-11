"""Inversiones: cada una con su propia contabilidad, sin mirar los movimientos del banco.

Lo aportado a una inversión son sus `Aportacion` (de la API de su plataforma o a mano); el
valor, la última ManualAssetEntry con su nombre, así /patrimonio la suma sin saber nada de
inversiones. /inversiones es el resumen de todas y cada plataforma con API tiene su módulo
(/inversiones/bit2me). Comparar con las transferencias del banco (Inversion.category_id)
es un paso aparte.
"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Aportacion, Posicion, Inversion, ManualAssetEntry
from app.services.net_worth_service import latest_manual_assets

MESES_RITMO = 12  # para "aportas X €/mes"
# Con menos de un año, anualizar exagera cualquier vaivén (un −0,5 % en tres semanas sale a
# −7 % anual): por debajo no se da TIR.
DIAS_MIN_TIR = 365
MODULOS = {
    "bit2me": "/inversiones/bit2me",
    "traderepublic": "/inversiones/trade-republic",
    "mediolanum": "/inversiones/pias",
    "ing": "/inversiones/plan-ing",
    "quanloop": "/inversiones/quanloop",
}  # proveedor -> página de su módulo
ORIGEN = {"mediolanum": "desde su web", "ing": "desde su web", "quanloop": "desde su web"}  # cómo llegan los datos, si no es por API


def inversion_de(db: Session, proveedor: str, nombre: str) -> Inversion:
    """La inversión de una plataforma con API; se crea si aún no existe."""
    inv = db.query(Inversion).filter_by(proveedor=proveedor).first()
    if inv is None:
        inv = Inversion(nombre=nombre, proveedor=proveedor)
        db.add(inv)
        db.flush()
    return inv


def ultima_foto(db: Session, inv: Inversion):
    return db.query(func.max(Posicion.recorded_at)).filter(Posicion.inversion_id == inv.id).scalar()


def inversiones(db: Session) -> list[Inversion]:
    return db.query(Inversion).order_by(Inversion.nombre).all()


def nombres(db: Session) -> set[str]:
    """Nombres de las inversiones: /patrimonio los separa del resto de activos declarados."""
    return {i.nombre for i in inversiones(db)}


def _hace_meses(hoy: date, meses: int) -> date:
    año, mes = divmod(hoy.year * 12 + hoy.month - 1 - meses, 12)
    return date(año, mes + 1, 1)


def tir(flujos: list[tuple[date, float]], valor: float, hoy: date) -> float | None:
    """Rentabilidad anual (TIR, en %) de unas aportaciones (fecha, importe; las retiradas en
    negativo) que hoy valen `valor`. Tiene en cuenta cuándo entró cada euro: no es lo mismo
    ganar un 13 % en seis años que en uno. None si la primera aportación tiene menos de
    DIAS_MIN_TIR días o no hay solución."""
    if not flujos or valor is None or (hoy - min(f for f, _ in flujos)).days < DIAS_MIN_TIR:
        return None

    def vf(tasa: float) -> float:  # lo aportado llevado a hoy a esa tasa, menos lo que vale
        return sum(i * (1 + tasa) ** ((hoy - f).days / 365.25) for f, i in flujos) - valor

    bajo, alto = -0.99, 10.0
    if vf(bajo) * vf(alto) > 0:
        return None
    for _ in range(200):  # bisección: vf crece con la tasa mientras se haya aportado neto
        medio = (bajo + alto) / 2
        if (vf(medio) > 0) == (vf(alto) > 0):
            alto = medio
        else:
            bajo = medio
    return (bajo + alto) / 2 * 100


def _flujos(db: Session) -> dict[int, list[tuple[date, float]]]:
    por_inversion: dict[int, list[tuple[date, float]]] = {}
    for iid, fecha, importe in db.query(Aportacion.inversion_id, Aportacion.fecha, Aportacion.importe):
        por_inversion.setdefault(iid, []).append((fecha, float(importe)))
    return por_inversion


def cartera(db: Session, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    invs = inversiones(db)
    aportes = {
        iid: (float(total), primera, n)
        for iid, total, primera, n in db.query(
            Aportacion.inversion_id, func.sum(Aportacion.importe), func.min(Aportacion.fecha), func.count()
        ).group_by(Aportacion.inversion_id)
    }
    recientes = dict(
        db.query(Aportacion.inversion_id, func.sum(Aportacion.importe))
        .filter(Aportacion.fecha >= _hace_meses(hoy, MESES_RITMO), Aportacion.fecha < hoy.replace(day=1))
        .group_by(Aportacion.inversion_id)
    )
    valores = {a["name"]: a for a in latest_manual_assets(db)}
    flujos = _flujos(db)

    filas = []
    for inv in invs:
        aportado, desde, n = aportes.get(inv.id, (None, None, 0))
        valor = valores.get(inv.nombre)
        fila = {
            "id": inv.id,
            "nombre": inv.nombre,
            "modulo": MODULOS.get(inv.proveedor),
            "origen": ORIGEN.get(inv.proveedor, "por API") if inv.proveedor else "módulo pendiente",
            "aportado": aportado,
            "aportaciones": n,
            "desde": desde,
            "ritmo_mensual": float(recientes.get(inv.id) or 0) / MESES_RITMO,
            "valor": valor["value"] if valor else None,
            "valor_fecha": valor["recorded_at"] if valor else None,
            "ganancia": None,
            "rentabilidad": None,
            "tir": None,
            "peso": None,
        }
        if valor is not None and aportado is not None:
            fila["ganancia"] = valor["value"] - aportado
            fila["rentabilidad"] = fila["ganancia"] / aportado * 100 if aportado > 0 else None
            fila["tir"] = tir(flujos.get(inv.id, []), valor["value"], hoy)
        filas.append(fila)

    total_valor = sum(f["valor"] for f in filas if f["valor"] is not None)
    for f in filas:
        if f["valor"] is not None and total_valor > 0:
            f["peso"] = f["valor"] / total_valor * 100
    completas = [f for f in filas if f["ganancia"] is not None]
    aportado_completas = sum(f["aportado"] for f in completas)
    ganancia = sum(f["ganancia"] for f in completas)
    filas.sort(key=lambda f: -(f["valor"] or 0))
    return {
        "filas": filas,
        "total_valor": total_valor,
        # La ganancia solo puede medirse donde hay valor y aportado: las demás no cuentan.
        "aportado_completas": aportado_completas,
        "ganancia": ganancia,
        "rentabilidad": ganancia / aportado_completas * 100 if aportado_completas > 0 else None,
        "tir": tir([f for c in completas for f in flujos.get(c["id"], [])], sum(c["valor"] for c in completas), hoy),
        "ritmo_mensual": sum(f["ritmo_mensual"] for f in filas),
        "incompletas": [f["nombre"] for f in filas if f["ganancia"] is None],
        "meses_ritmo": MESES_RITMO,
    }


def evolucion(db: Session, inv: Inversion) -> list[dict]:
    """Cada valor apuntado de una inversión junto a lo aportado hasta ese día. Con varias
    fotos al día (Bit2Me sincroniza a menudo) se queda la última de cada día."""
    aportes = db.query(Aportacion.fecha, Aportacion.importe).filter_by(inversion_id=inv.id).all()
    por_dia: dict[date, float] = {}
    for fila in db.query(ManualAssetEntry).filter_by(name=inv.nombre).order_by(ManualAssetEntry.recorded_at):
        por_dia[fila.recorded_at.date()] = float(fila.value)
    return [
        {"fecha": dia.isoformat(), "valor": valor,
         "aportado": sum(float(a.importe) for a in aportes if a.fecha <= dia)}
        for dia, valor in por_dia.items()
    ]


def modulo(db: Session, inv: Inversion) -> dict:
    """Módulo de una plataforma (Bit2Me, Trade Republic): totales, cada activo de la última
    foto con su ganancia o pérdida, y de dónde sale el resultado (activos, ventas, comisiones)."""
    aportaciones = db.query(Aportacion).filter_by(inversion_id=inv.id).order_by(Aportacion.fecha.desc()).all()
    aportado = sum(float(a.importe) for a in aportaciones)
    ultima = ultima_foto(db, inv)
    filas = db.query(Posicion).filter_by(inversion_id=inv.id, recorded_at=ultima).all() if ultima else []

    valor = sum(float(f.valor_eur) for f in filas)
    monedas, euros = [], None
    for f in filas:
        cantidad, coste = float(f.cantidad), float(f.coste_eur or 0)
        recompensas = float(f.recompensas or 0)
        fila = {
            "symbol": f.symbol,
            "nombre": f.nombre or f.symbol,
            "cantidad": cantidad,
            "precio": float(f.precio_eur),
            "valor": float(f.valor_eur),
            "coste": coste,
            "latente": float(f.valor_eur) - coste,
            "latente_pct": (float(f.valor_eur) - coste) / coste * 100 if coste > 0 else None,
            "realizado": float(f.realizado_eur or 0),
            "recompensas": recompensas,
            # Precio medio de lo comprado que queda (las recompensas no costaron nada).
            "precio_medio": coste / (cantidad - recompensas) if cantidad - recompensas > 0 else None,
            "peso": float(f.valor_eur) / valor * 100 if valor > 0 else 0.0,
        }
        if f.symbol == "EUR":
            euros = fila
        else:
            monedas.append(fila)
    monedas.sort(key=lambda m: -m["valor"])

    ganancia = valor - aportado
    latente = sum(m["latente"] for m in monedas)
    realizado = sum(m["realizado"] for m in monedas)
    return {
        "inversion": inv,
        "ultima": ultima,
        "aportado": aportado,
        "aportaciones": aportaciones,
        "valor": valor,
        "ganancia": ganancia,
        "rentabilidad": ganancia / aportado * 100 if aportado > 0 else None,
        "tir": tir([(a.fecha, float(a.importe)) for a in aportaciones], valor, date.today()) if filas else None,
        "monedas": monedas,
        "euros": euros,
        "latente": latente,
        "realizado": realizado,
        # Lo que no explican ni las monedas ni las ventas: comisiones de tarjeta y las
        # cobradas en la propia cripto.
        "comisiones": latente + realizado - ganancia,
        "evolucion": evolucion(db, inv),
    }
