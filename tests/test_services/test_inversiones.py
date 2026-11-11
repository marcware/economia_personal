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
