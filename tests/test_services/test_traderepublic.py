"""Trade Republic: de lo que devuelve su API a ingresos y posiciones, sin llamar a la API."""

from datetime import date

import pytest

from app.integrations.bit2me import sync_service as bit2me_sync
from app.integrations.traderepublic import client, sync_service
from app.models import Aportacion, Posicion
from app.services import inversiones_service


def _mov(id, dia, tipo, importe, estado="EXECUTED"):
    return {"id": id, "timestamp": f"{dia}T10:00:00.000+0000", "title": "Fco", "subtitle": "",
            "eventType": tipo, "status": estado, "amount": {"currency": "EUR", "value": importe}}


DATOS = {
    "posiciones": [
        {"instrumentId": "IE00B4ND3602", "name": "Physical Gold", "netSize": "0.5", "averageBuyIn": "100", "price": "110"},
        {"instrumentId": "XX0000000000", "name": "Sin precio", "netSize": "1", "averageBuyIn": "5"},
        {"instrumentId": "YY0000000000", "name": "Vendido", "netSize": "0", "averageBuyIn": "5", "price": "6"},
    ],
    "efectivo": [{"currencyId": "EUR", "amount": 40.0}],
    "movimientos": [
        _mov("a", "2026-10-21", "BANK_TRANSACTION_INCOMING", 100.0),
        _mov("b", "2026-10-22", "TRADING_TRADE_EXECUTED", -51.0),  # comprar con el saldo: interno
        _mov("c", "2026-11-01", "CARD_SUCCESSFUL_TRANSACTION", -10.0),  # pagar con su tarjeta: sale
        _mov("d", "2026-11-02", "BANK_TRANSACTION_INCOMING", 999.0, estado="CANCELED"),
    ],
}


def test_calcular_ingresos_y_posiciones():
    r = sync_service.calcular(DATOS)
    assert [(a["id"], a["importe"]) for a in r["aportaciones"]] == [("a", 100.0), ("c", -10.0)]
    p = {x["symbol"]: x for x in r["posiciones"]}
    assert set(p) == {"IE00B4ND3602", "EUR"}
    assert (p["IE00B4ND3602"]["valor"], p["IE00B4ND3602"]["coste"]) == (55.0, 50.0)
    assert p["EUR"]["valor"] == 40.0
    assert any("Sin precio" in a for a in r["avisos"])


def test_sincronizar_sin_duplicar_y_sin_mezclar_con_bit2me(db):
    otra = bit2me_sync.inversion(db)
    db.add(Posicion(inversion_id=otra.id, symbol="BTC", cantidad=1, precio_eur=1, valor_eur=1))
    db.commit()

    r = sync_service.sincronizar(db, DATOS)
    assert r["total"] == pytest.approx(95.0)
    assert sync_service.sincronizar(db, DATOS)["aportaciones_nuevas"] == 0
    assert db.query(Aportacion).count() == 2

    m = inversiones_service.modulo(db, sync_service.inversion(db))
    assert [c["symbol"] for c in m["monedas"]] == ["IE00B4ND3602"]
    assert m["aportado"] == pytest.approx(90.0)
    assert m["ganancia"] == pytest.approx(5.0)
    assert m["monedas"][0]["precio_medio"] == pytest.approx(100.0)
    assert m["aportaciones"][0].fecha == date(2026, 11, 1)


def test_el_lector_no_deja_operar():
    class Api:
        def market_order(self, *a):
            return "orden enviada"

    with pytest.raises(AttributeError):
        client.Lector(Api()).market_order("IE00B4ND3602", "buy", 1)
