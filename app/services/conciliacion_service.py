"""Comparación de cada inversión con el banco: lo que salió de tus cuentas hacia la
plataforma (movimientos en la categoría de `Inversion.category_id`) frente a lo que la
plataforma dice haber recibido (sus `Aportacion`).

Es el único sitio de /inversiones que mira el banco, y solo para comparar: lo aportado y la
ganancia siguen saliendo de la plataforma. La diferencia en los movimientos que casan son
gastos que se quedan por el camino (los de entrada del PIAS); los que no casan son
transferencias sin categorizar, de otra cuenta o de antes de que el banco esté conectado.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Aportacion, Inversion, Transaction
from app.services.inversiones_service import tir

DIAS = 7  # entre el cargo en el banco y la llegada a la plataforma
TOLERANCIA = 0.2  # diferencia de importe aceptable al casar (gastos de entrada, redondeos)
DIAS_CANDIDATO = 4  # para buscar el cargo sin categorizar de una aportación que no casa


def _inicio_banco(db: Session, cuentas: set[int]) -> date | None:
    """Desde cuándo hay movimientos del banco: de las cuentas que han pagado la inversión o,
    si ninguna, de la primera cuenta conectada."""
    consulta = db.query(func.min(Transaction.date))
    if cuentas:
        consulta = consulta.filter(Transaction.account_id.in_(cuentas))
    return consulta.scalar()


def conciliar(db: Session, inv: Inversion) -> dict:
    banco = []
    if inv.category_id:
        banco = (db.query(Transaction).filter(Transaction.category_id == inv.category_id)
                 .order_by(Transaction.date).all())
    desde = _inicio_banco(db, {t.account_id for t in banco})

    # La plataforma puede partir un ingreso en varias filas (el PIAS, una por fondo): se
    # suman por día.
    por_dia: dict[date, float] = defaultdict(float)
    for a in db.query(Aportacion).filter(Aportacion.inversion_id == inv.id):
        por_dia[a.fecha] += float(a.importe)
    plataforma = [{"fecha": f, "importe": round(i, 2)} for f, i in sorted(por_dia.items())
                  if desde is None or f >= desde - timedelta(days=DIAS)]

    # Del lado del banco también por día: dos pagos con tarjeta el mismo día pueden llegar como
    # un solo ingreso, y al revés.
    cargos: dict[date, dict] = {}
    for t in banco:
        dia = cargos.setdefault(t.date, {"fecha": t.date, "importe": 0.0, "conceptos": []})
        dia["importe"] += -float(t.amount)
        dia["conceptos"].append(t.description_raw)

    # Casar cada día de cargos con la llegada a la plataforma más parecida (importe, luego fecha).
    libres = list(plataforma)
    casados, solo_banco = [], []
    for c in cargos.values():
        salida, concepto = round(c["importe"], 2), " · ".join(dict.fromkeys(c["conceptos"]))
        opciones = [p for p in libres if abs((p["fecha"] - c["fecha"]).days) <= DIAS
                    and (salida > 0) == (p["importe"] > 0)
                    and abs(p["importe"] - salida) <= TOLERANCIA * abs(salida)]
        if not opciones:
            solo_banco.append({"fecha": c["fecha"], "importe": salida, "concepto": concepto})
            continue
        p = min(opciones, key=lambda p: (abs(p["importe"] - salida), abs((p["fecha"] - c["fecha"]).days)))
        libres.remove(p)
        casados.append({"fecha": c["fecha"], "banco": salida, "plataforma": p["importe"],
                        "diferencia": round(salida - p["importe"], 2), "concepto": concepto})

    # Lo que la plataforma recibió sin cargo en esa categoría: busca un cargo sin categorizar
    # del mismo importe esos días, que será el que falta. Solo sin categorizar: uno ya
    # categorizado (un Bizum de 50 €) es otra cosa aunque coincida el importe.
    usados = {t.id for t in banco}
    solo_plataforma = []
    for p in libres:
        candidato = None
        if desde and p["fecha"] >= desde and p["importe"] > 0:
            candidato = (db.query(Transaction)
                         .filter(Transaction.amount == -p["importe"],
                                 Transaction.date.between(p["fecha"] - timedelta(days=DIAS_CANDIDATO),
                                                          p["fecha"] + timedelta(days=DIAS_CANDIDATO)),
                                 Transaction.category_id.is_(None), Transaction.id.notin_(usados))
                         .order_by(func.abs(func.julianday(Transaction.date)
                                                                                - func.julianday(p["fecha"])))
                         .first())
            if candidato:
                usados.add(candidato.id)
        solo_plataforma.append({**p, "antes_del_banco": desde is not None and p["fecha"] < desde,
                                "candidato": candidato})

    pagado = sum(c["banco"] for c in casados)
    recibido = sum(c["plataforma"] for c in casados)
    return {
        "inversion": inv,
        "desde": desde,
        "casados": casados,
        "solo_banco": solo_banco,
        "solo_plataforma": solo_plataforma,
        "pagado": round(pagado, 2),
        "recibido": round(recibido, 2),
        "gastos": round(pagado - recibido, 2),
        "gastos_pct": (pagado - recibido) / pagado * 100 if pagado else None,
        "sin_categorizar": [s for s in solo_plataforma if s["candidato"] is not None],
    }


def conciliar_todas(db: Session) -> list[dict]:
    return [conciliar(db, inv) for inv in db.query(Inversion).order_by(Inversion.nombre)]


def categorizar_pendientes(db: Session, inv: Inversion) -> int:
    """Pone en la categoría de la inversión los cargos sin categorizar que casan con
    aportaciones de la plataforma (ver `conciliar`). Como si lo hubieras hecho a mano."""
    if not inv.category_id:
        return 0
    pendientes = [s["candidato"] for s in conciliar(db, inv)["sin_categorizar"]]
    for t in pendientes:
        t.category_id = inv.category_id
        t.manually_categorized = True
    db.commit()
    return len(pendientes)


def estimar_historico(db: Session, inv: Inversion, conc: dict, valor: float) -> dict | None:
    """Si casan cargos con gastos (el PIAS), lo que habría salido del banco en toda la vida de
    la inversión suponiendo el mismo % en cada aportación, y su rentabilidad anual medida
    sobre ese dinero (el que de verdad pusiste). Una estimación: el banco no llega tan atrás."""
    if not conc["gastos_pct"] or conc["gastos_pct"] <= 0:
        return None
    factor = 1 / (1 - conc["gastos_pct"] / 100)
    flujos = [(a.fecha, float(a.importe) * factor if a.importe > 0 else float(a.importe))
              for a in db.query(Aportacion).filter(Aportacion.inversion_id == inv.id)]
    neto = sum(float(a.importe) for a in db.query(Aportacion).filter(Aportacion.inversion_id == inv.id))
    pagado = sum(i for _, i in flujos)
    return {"pagado": round(pagado, 2), "gastos": round(pagado - neto, 2), "ganancia": round(valor - pagado, 2),
            "tir": tir(flujos, valor, date.today())}
