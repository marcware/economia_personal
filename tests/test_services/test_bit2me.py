"""Bit2Me: firma de las peticiones, coste de cada moneda y la foto de la cartera, sin
llamar a la API real."""

from datetime import date, datetime

import pytest

from app.integrations.bit2me import cartera, sync_service
from app.integrations.bit2me.client import firma
from app.models import Aportacion, Posicion, ManualAssetEntry
from app.services import inversiones_service


def test_firma_como_la_del_mcp_oficial():
    # Vector generado con generateSignature() de bit2me-devs/bit2me-mcp (Node).
    esperada = "MtkC/EOPkqAA8lPT2VR3QOGp+E3er908p9qj1V7omjOU6V6rRvLCVHntUIQ6uTNEcVN0DlEf0mHARKQX6n+C9w=="
    assert firma(1700000000000, "/v1/wallet/pocket", "secreto-de-prueba") == esperada


def _op(id, fecha, tipo, origen, destino):
    lado = lambda cantidad, moneda, clase: {"amount": str(cantidad), "currency": moneda, "class": clase}  # noqa: E731
    return {"id": id, "date": f"{fecha}T10:00:00Z", "type": tipo, "status": "completed",
            "origin": lado(*origen), "destination": lado(*destino)}


OPERACIONES = [
    _op("a", "2025-01-01", "deposit", (100, "EUR", "card"), (1.0, "BTC", "pocket")),  # compra con tarjeta
    _op("b", "2025-01-02", "withdrawal", (1.0, "BTC", "pocket"), (1.0, "BTC", "earn")),  # interno
    _op("c", "2025-02-01", "deposit", (50, "EUR", "card"), (49, "EUR", "pocket")),  # recarga: 1 € de comisión
    _op("d", "2025-02-02", "transfer", (40, "EUR", "pocket"), (1.0, "BTC", "pocket")),
    _op("e", "2025-03-01", "transfer", (1.0, "BTC", "pocket"), (150, "EUR", "pocket")),  # vende lo de 100 €
    _op("f", "2025-04-01", "deposit", (30, "EUR", "bank-transfer"), (30, "EUR", "pocket")),
    _op("g", "2025-04-02", "withdrawal", (20, "EUR", "pocket"), (20, "EUR", "trading")),  # a Pro: interno
    _op("h", "2025-05-01", "withdrawal", (60, "EUR", "pocket"), (60, "EUR", "bank-transfer")),  # a la cuenta
]
TRADES = [{"symbol": "ETH/EUR", "side": "buy", "amount": 0.01, "cost": 20, "createdAt": "2025-04-03T00:00:00Z"}]


def test_coste_fifo_ventas_recompensas_y_comisiones():
    r = cartera.calcular(OPERACIONES, TRADES, {"BTC": 1.25, "ETH": 0.01, "EUR": 109})
    assert [(a["id"], a["importe"]) for a in r["aportaciones"]] == [("a", 100), ("c", 50), ("f", 30), ("h", -60)]
    assert r["comisiones"] == pytest.approx(1.0)
    p = {x["symbol"]: x for x in r["posiciones"]}
    assert p["BTC"]["realizado"] == pytest.approx(50.0)  # FIFO: vende el BTC de 100 € por 150 €
    assert p["BTC"]["coste"] == pytest.approx(40.0)
    assert p["BTC"]["recompensas"] == pytest.approx(0.25)  # Earn, a coste cero
    assert p["ETH"]["coste"] == pytest.approx(20.0)  # comprado en Pro


class ClienteFalso:
    def saldos(self):
        return {"BTC": 1.25, "ETH": 0.01, "EUR": 109.0, "RARA": 10.0}, []

    def operaciones(self):
        return OPERACIONES

    def trades_pro(self):
        return TRADES

    def precio_eur(self, simbolo):
        return {"BTC": 100.0, "ETH": 3000.0, "EUR": 1.0}.get(simbolo)


def test_sincronizar_guarda_aportaciones_sin_duplicar_y_posiciones(db):
    r = sync_service.sincronizar(db, ClienteFalso())
    assert r["total"] == pytest.approx(125 + 30 + 109)
    assert r["aportaciones_nuevas"] == 4
    assert any("RARA" in a for a in r["avisos"])
    assert sync_service.sincronizar(db, ClienteFalso())["aportaciones_nuevas"] == 0
    assert db.query(Aportacion).count() == 4

    m = inversiones_service.modulo(db, sync_service.inversion(db))
    assert m["aportado"] == pytest.approx(120.0)
    assert m["valor"] == pytest.approx(264.0)
    assert [c["symbol"] for c in m["monedas"]] == ["BTC", "ETH"]
    assert m["euros"]["valor"] == pytest.approx(109.0)
    # El total se explica entero: monedas + ventas − comisiones.
    assert m["latente"] + m["realizado"] - m["comisiones"] == pytest.approx(m["ganancia"])
    assert m["comisiones"] == pytest.approx(1.0)


def test_sin_clave_no_sincroniza(db, monkeypatch):
    monkeypatch.setattr(sync_service, "configurado", lambda: False)
    assert sync_service.sincronizar_si_toca(db) is None
    assert db.query(Posicion).count() == 0


def test_evolucion_valor_frente_a_aportado(db):
    inv = sync_service.inversion(db)
    db.add_all([
        Aportacion(inversion_id=inv.id, fecha=date(2026, 10, 8), importe=25),
        Aportacion(inversion_id=inv.id, fecha=date(2026, 11, 8), importe=25),
    ])
    for cuando, valor in ((datetime(2026, 10, 20, 9), 20), (datetime(2026, 10, 20, 18), 22), (datetime(2026, 11, 10, 9), 55)):
        db.add(ManualAssetEntry(name="Bit2Me", value=valor, recorded_at=cuando))
    db.commit()

    assert inversiones_service.evolucion(db, inv) == [
        {"fecha": "2026-10-20", "valor": 22.0, "aportado": 25.0},
        {"fecha": "2026-11-10", "valor": 55.0, "aportado": 50.0},
    ]
