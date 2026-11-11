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

from app.models import Aportacion, CriptoPosicion, Inversion, ManualAssetEntry
from app.services.net_worth_service import latest_manual_assets

MESES_RITMO = 12  # para "aportas X €/mes"
MODULOS = {"bit2me": "/inversiones/bit2me"}  # proveedor -> página de su módulo


def inversiones(db: Session) -> list[Inversion]:
    return db.query(Inversion).order_by(Inversion.nombre).all()


def nombres(db: Session) -> set[str]:
    """Nombres de las inversiones: /patrimonio los separa del resto de activos declarados."""
    return {i.nombre for i in inversiones(db)}


def _hace_meses(hoy: date, meses: int) -> date:
    año, mes = divmod(hoy.year * 12 + hoy.month - 1 - meses, 12)
    return date(año, mes + 1, 1)


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

    filas = []
    for inv in invs:
        aportado, desde, n = aportes.get(inv.id, (None, None, 0))
        valor = valores.get(inv.nombre)
        fila = {
            "id": inv.id,
            "nombre": inv.nombre,
            "modulo": MODULOS.get(inv.proveedor),
            "aportado": aportado,
            "aportaciones": n,
            "desde": desde,
            "ritmo_mensual": float(recientes.get(inv.id) or 0) / MESES_RITMO,
            "valor": valor["value"] if valor else None,
            "valor_fecha": valor["recorded_at"] if valor else None,
            "ganancia": None,
            "rentabilidad": None,
            "peso": None,
        }
        if valor is not None and aportado is not None:
            fila["ganancia"] = valor["value"] - aportado
            fila["rentabilidad"] = fila["ganancia"] / aportado * 100 if aportado > 0 else None
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


def modulo_cripto(db: Session, inv: Inversion) -> dict:
    """Módulo de una plataforma cripto (Bit2Me): totales, cada moneda de la última foto con
    su ganancia o pérdida, y de dónde sale el resultado (monedas, ventas, comisiones)."""
    aportaciones = db.query(Aportacion).filter_by(inversion_id=inv.id).order_by(Aportacion.fecha.desc()).all()
    aportado = sum(float(a.importe) for a in aportaciones)
    ultima = db.query(func.max(CriptoPosicion.recorded_at)).scalar()
    filas = db.query(CriptoPosicion).filter_by(recorded_at=ultima).all() if ultima else []

    valor = sum(float(f.valor_eur) for f in filas)
    monedas, euros = [], None
    for f in filas:
        cantidad, coste = float(f.cantidad), float(f.coste_eur or 0)
        recompensas = float(f.recompensas or 0)
        fila = {
            "symbol": f.symbol,
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
        "monedas": monedas,
        "euros": euros,
        "latente": latente,
        "realizado": realizado,
        # Lo que no explican ni las monedas ni las ventas: comisiones de tarjeta y las
        # cobradas en la propia cripto.
        "comisiones": latente + realizado - ganancia,
        "evolucion": evolucion(db, inv),
    }
