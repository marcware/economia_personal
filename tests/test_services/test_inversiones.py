"""Resumen de /inversiones: cada inversión con su propia contabilidad, sin el banco."""

from datetime import date, datetime

import pytest

from app.models import Aportacion, Inversion, ManualAssetEntry
from app.services import inversiones_service

HOY = date(2026, 11, 11)


def test_aportado_valor_y_ganancia(db, movimiento):
    bit2me = Inversion(nombre="Bit2Me", proveedor="bit2me")
    quanloop = Inversion(nombre="Quanloop")
    plan = Inversion(nombre="Plan de pensiones ING")
    db.add_all([bit2me, quanloop, plan])
    db.flush()
    db.add_all([
        Aportacion(inversion_id=bit2me.id, fecha=date(2026, 9, 8), importe=25),
        Aportacion(inversion_id=bit2me.id, fecha=date(2026, 10, 8), importe=25),
        Aportacion(inversion_id=bit2me.id, fecha=date(2026, 10, 20), importe=-10),  # sacado a la cuenta
        Aportacion(inversion_id=bit2me.id, fecha=date(2026, 11, 8), importe=25),  # mes en curso: fuera del ritmo
        ManualAssetEntry(name="Bit2Me", value=90),
        ManualAssetEntry(name="Plan de pensiones ING", value=6000, recorded_at=datetime(2026, 9, 1)),
        ManualAssetEntry(name="Plan de pensiones ING", value=6200, recorded_at=datetime(2026, 11, 1)),
    ])
    db.commit()

    c = inversiones_service.cartera(db, HOY)
    filas = {f["nombre"]: f for f in c["filas"]}
    assert filas["Bit2Me"]["aportado"] == pytest.approx(65.0)
    assert filas["Bit2Me"]["ganancia"] == pytest.approx(25.0)
    assert filas["Bit2Me"]["modulo"] == "/inversiones/bit2me"
    assert filas["Bit2Me"]["ritmo_mensual"] == pytest.approx(40 / 12)
    # Sin aportaciones no hay ganancia, aunque haya valor (y nada sale del banco).
    assert filas["Plan de pensiones ING"]["valor"] == pytest.approx(6200.0)
    assert filas["Plan de pensiones ING"]["ganancia"] is None
    assert filas["Quanloop"]["valor"] is None
    assert c["total_valor"] == pytest.approx(6290.0)
    assert c["ganancia"] == pytest.approx(25.0)
    assert sorted(c["incompletas"]) == ["Plan de pensiones ING", "Quanloop"]
    assert inversiones_service.nombres(db) == {"Bit2Me", "Quanloop", "Plan de pensiones ING"}


def test_pias_lee_portada_y_extracto():
    from app.integrations.mediolanum import pias

    portada = '<a aria-label="Elemento 1 de 1. FUTURO EXTRA PIAS, (PAC). Póliza: 999 . Saldo 1.234 euros con 5 céntimos">'
    assert pias.polizas(portada) == [{"poliza": "999", "saldo": 1234.05}]

    def fila(fecha, concepto, part, precio, importe):
        return (f"<tr><TD>{fecha}</TD><TD colspan='2'>{concepto}</TD><TD>{part}</TD>"
                f"<TD>{precio}</TD><TD>{importe}</TD></tr>")

    pagina = ('<table id="tblExtracto"><tr><td colSpan="6">Consulta de extracto</td></tr>'
              "<tr><TD colspan='6'>FONDO A</TD></tr>" + fila("02/02/2026", "SUSCRIPCION", "10,000", "10,000", "100,00")
              + "<tr><TD colspan='6'>FONDO A</TD></tr>" + fila("02/05/2026", "Gastos de admón.", "1,000", "11,000", "-11,00")
              + "<tr><TD colspan='6'>FONDO A</TD></tr>" + fila("03/05/2026", "ABONO FIDELIDAD MILL", "0,500", "11,000", "5,50")
              + "</table>")
    filas = pias.extracto(pagina)
    assert [(f["fondo"], f["concepto"], f["importe"]) for f in filas] == [
        ("FONDO A", "SUSCRIPCION", 100.0), ("FONDO A", "Gastos de admón.", -11.0),
        ("FONDO A", "ABONO FIDELIDAD MILL", 5.5)]

    r = pias.calcular(120.0, filas)
    assert [a["importe"] for a in r["aportaciones"]] == [100.0]  # los gastos no son dinero que vuelve
    assert r["gastos"] == pytest.approx(11.0)
    (fondo,) = r["posiciones"]
    assert fondo["cantidad"] == pytest.approx(9.5)  # 10 − 1 de gastos + 0,5 regaladas
    assert fondo["recompensas"] == pytest.approx(0.5)
    assert r["avisos"] == []
    assert fondo["valor"] == pytest.approx(120.0)  # se ajusta al saldo real
    # valor − aportado = (valor − coste) + realizado
    assert (fondo["valor"] - fondo["coste"]) + fondo["realizado"] == pytest.approx(120.0 - 100.0)


def test_plan_ing_aportaciones_y_pendiente_de_valorar():
    from app.integrations.ing import plan_pensiones as pp

    posicion = {"products": [
        {"type": "CURRENT_ACCOUNT", "balanceToShow": 10.0, "identifiers": []},
        {"type": "PENSION", "commercialName": "Plan 2050", "balanceToShow": 330.0, "openingDate": "2019-01-07",
         "identifiers": [{"type": "LOCAL_UUID", "value": "abc"}]},
    ]}
    plan = pp.plan(posicion)
    assert (plan["nombre"], plan["saldo"], plan["id"]) == ("Plan 2050", 330.0, "abc")

    def mov(uuid, fecha, importe, part, estado="Orden realizada"):
        return {"uuid": uuid, "operationDate": fecha, "tranCode": "SUSC", "description": "Aportaciones periódicas",
                "amount": importe, "sharesNumbers": part, "status": estado}

    r = pp.calcular(330.0, [mov("1", "10/01/2026", 100, 10), mov("2", "10/02/2026", 200, 18),
                            mov("3", "10/03/2026", 125, 0, "Correcta. Cargada en cuenta. Pendiente valoración")])
    assert sum(a["importe"] for a in r["aportaciones"]) == 425
    plan_pos, pendiente = r["posiciones"]
    assert (plan_pos["cantidad"], plan_pos["coste"], plan_pos["valor"]) == (28, 300, 330.0)
    assert (pendiente["symbol"], pendiente["valor"]) == ("EUR", 125)  # cargada pero aún sin participaciones


def test_quanloop_ingresos_intereses_y_planes():
    from app.integrations.quanloop import cuenta as ql

    informe = "<td>11.11.2026</td><td>€1,160</td> <div>Low risk</div><div>Medium risk</div><div>High risk</div>" \
              "<span>€870</span><span>€290</span><span>€0</span>"
    panel = "<p>Profit payout (15.11.2026)</p><b>€9.15</b><p>Profit payout (15.12.2026)</p><b>€3.34</b>"
    assert ql.planes(informe) == {"LOW": 870.0, "MEDIUM": 290.0, "HIGH": 0.0}
    assert ql.por_cobrar(panel) == 12.49

    extracto = {"endBalance": 1160.70, "entries": [
        {"id": 1, "date": "2024-01-05", "type": "TOPUP", "amount": 1150.0},
        {"id": 2, "date": "2024-08-07", "type": "WITHDRAWAL", "amount": -13.27},
        {"id": 3, "date": "2026-10-15", "type": "INTEREST_PAYOUT", "amount": 23.96},
        {"id": 4, "date": "2026-09-01", "type": "CASHBACK_PAYOUT", "amount": 0.01},
    ]}
    r = ql.calcular(extracto, ql.planes(informe), ql.por_cobrar(panel))
    assert [a["importe"] for a in r["aportaciones"]] == [1150.0, -13.27]  # los intereses no son dinero metido
    assert r["cobrado"] == 23.97 and not r["avisos"]
    valores = {p["symbol"]: p["valor"] for p in r["posiciones"]}
    assert valores == {"LOW": 870.0, "MEDIUM": 290.0, "EUR": 0.7, "PENDIENTE": 12.49}
