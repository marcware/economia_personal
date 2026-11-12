"""La aritmética de dinero que más duele si se rompe: gasto neto, qué es ingreso, ciclo de
nómina, el "libre" de la portada y la copia de presupuestos."""

from datetime import date, datetime, timedelta

import pytest

from app.categorization.seed_rules import CATEGORY_TREE
from app.models import Account, AccountBalance, Bank, Budget, BudgetGroup, RolCuenta
from app.services import budget_service, dashboard_service, disponible_service

HOY = date(2026, 10, 5)


def test_gasto_neto_de_devoluciones(db, categoria, movimiento):
    gasolina = categoria("Gasolina", BudgetGroup.NECESIDAD)
    inversion = categoria("Inversión", BudgetGroup.AHORRO)
    movimiento(date(2026, 9, 3), -50, gasolina)
    movimiento(date(2026, 9, 10), 35, gasolina)  # un Bizum que devuelve su parte
    movimiento(date(2026, 9, 12), -80, gasolina, traspaso=True)  # un traspaso no es gasto
    movimiento(date(2026, 9, 5), -100, inversion)
    movimiento(date(2026, 9, 20), 40, inversion)  # un reembolso de inversión no resta
    movimiento(date(2026, 10, 2), 35, gasolina)  # devolución sin cargo en el mes

    septiembre = budget_service.month_expense_by_category(db, 2026, 9)
    assert septiembre[gasolina.id] == pytest.approx(15.0)
    assert septiembre[inversion.id] == pytest.approx(100.0)
    assert budget_service.month_expense_by_category(db, 2026, 10)[gasolina.id] == pytest.approx(-35.0)


def test_un_prestamo_abonado_no_es_ingreso(db, categoria, movimiento):
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    prestamos = categoria("Préstamos", BudgetGroup.NECESIDAD, recurrente=True)
    movimiento(date(2026, 9, 10), 3000, nomina)
    movimiento(date(2026, 9, 8), 2000, prestamos)  # el banco abona el préstamo
    movimiento(date(2026, 9, 3), -411.77, prestamos)

    s = dashboard_service.monthly_summary(db, 2026, 9)
    assert s["ingresos"] == pytest.approx(3000.0)
    assert s["otros_abonos"] == pytest.approx(2000.0)
    assert s["gastos"] == pytest.approx(411.77)
    assert s["ahorro"] == pytest.approx(2588.23)
    assert dashboard_service.evolution(db, 1)[0]["ingresos"] == pytest.approx(3000.0)


def test_un_prestamo_abonado_no_resta_de_las_cuotas(db, categoria, movimiento):
    grupos = {(padre, hoja): grupo for padre, hoja, grupo, *_ in CATEGORY_TREE}
    assert grupos[("Otros ingresos", "Abono de financiación")] == BudgetGroup.EXCLUIDO
    cuotas = categoria("Otros préstamos y avales", BudgetGroup.NECESIDAD, recurrente=True)
    abono = categoria("Abono de financiación", BudgetGroup.EXCLUIDO)
    movimiento(date(2026, 9, 8), 2000, abono)
    movimiento(date(2026, 9, 3), -411.77, cuotas)

    gasto = budget_service.month_expense_by_category(db, 2026, 9)
    assert gasto[cuotas.id] == pytest.approx(411.77)
    assert abono.id not in gasto
    assert dashboard_service.monthly_summary(db, 2026, 9)["ingresos"] == pytest.approx(0.0)


def test_la_nomina_de_final_de_mes_cuenta_en_el_que_paga(db, categoria, movimiento):
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    alquiler = categoria("Alquiler", BudgetGroup.INGRESO)
    super_ = categoria("Supermercado", BudgetGroup.NECESIDAD)
    movimiento(date(2026, 9, 28), 2858.39, nomina)  # paga octubre
    movimiento(date(2026, 10, 8), 400, alquiler)
    movimiento(date(2026, 9, 29), -100, super_)  # el gasto va por mes natural

    octubre = dashboard_service.monthly_summary(db, 2026, 10)
    assert octubre["ingresos"] == pytest.approx(3258.39)
    assert octubre["gastos"] == pytest.approx(0.0)
    septiembre = dashboard_service.monthly_summary(db, 2026, 9)
    assert (septiembre["ingresos"], septiembre["gastos"]) == (0.0, 100.0)
    assert [e["label"] for e in dashboard_service.evolution(db)] == ["2026-09", "2026-10"]


def test_ciclo_de_nomina(db, categoria, movimiento):
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    for mes in (7, 8):
        movimiento(date(2026, mes, 27), 2858.39, nomina)
    movimiento(date(2026, 9, 28), 2858.39, nomina)
    movimiento(date(2026, 10, 1), 35, nomina)  # un abono pequeño en la misma categoría no abre ciclo

    ciclo = disponible_service.ciclo_nomina(db, HOY)
    assert (ciclo["inicio"], ciclo["siguiente"]) == (date(2026, 9, 28), date(2026, 10, 28))
    assert ciclo["detectada"] and not ciclo["retrasada"]

    assert disponible_service.ciclo_nomina(db, date(2026, 10, 30))["retrasada"]


def test_ciclo_sin_nomina_cae_al_mes_natural(db):
    ciclo = disponible_service.ciclo_nomina(db, HOY)
    assert (ciclo["inicio"], ciclo["siguiente"]) == (date(2026, 10, 1), date(2026, 11, 1))
    assert not ciclo["detectada"]


def test_fin_de_mes_no_se_sale_del_calendario():
    assert disponible_service._sumar_mes(date(2027, 1, 30)) == date(2027, 2, 28)
    assert disponible_service._sumar_mes(date(2026, 12, 27)) == date(2027, 1, 27)
    assert budget_service._hace_un_año(date(2028, 2, 29)) == date(2027, 2, 28)


def test_libre_hasta_la_nomina(db, cuenta, categoria, movimiento):
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    hipoteca = categoria("Hipoteca", BudgetGroup.NECESIDAD, recurrente=True)
    luz = categoria("Luz", BudgetGroup.NECESIDAD, recurrente=True)
    super_ = categoria("Supermercado", BudgetGroup.NECESIDAD)
    restaurantes = categoria("Restaurantes", BudgetGroup.DESEO)

    mediolanum = Account(bank=Bank.MEDIOLANUM, name="Mediolanum")
    db.add(mediolanum)
    db.flush()
    db.add_all([
        AccountBalance(account_id=cuenta.id, balance=2000, recorded_at=datetime(2026, 10, 5, 8)),
        AccountBalance(account_id=mediolanum.id, balance=9999, recorded_at=datetime(2026, 10, 5, 8)),
        Budget(category_id=hipoteca.id, year=2026, month=10, monthly_limit=276.38),
        Budget(category_id=luz.id, year=2026, month=10, monthly_limit=128),
        Budget(category_id=super_.id, year=2026, month=10, monthly_limit=120),
        Budget(category_id=restaurantes.id, year=2026, month=10, monthly_limit=70),
    ])
    db.commit()

    movimiento(date(2026, 9, 28), 2858.39, nomina, en=mediolanum)
    movimiento(date(2026, 10, 1), -276.38, hipoteca)  # ya pagada en este ciclo
    for mes in (7, 8, 9):  # el súper cuesta 200 € de verdad, no los 120 presupuestados
        movimiento(date(2026, mes, 10), -200, super_)
    movimiento(date(2026, 10, 3), -50, super_)

    d = disponible_service.disponible(db, HOY)

    assert d["mes_presupuesto"] == (2026, 10)
    assert d["saldo"] == pytest.approx(2000.0)  # Mediolanum no cuenta
    assert d["total_fijos"] == pytest.approx(128.0)  # solo queda la luz
    assert d["total_variables"] == pytest.approx(150.0)  # 200 habituales - 50 ya gastados
    assert [f["origen"] for f in d["variables_necesarios"]] == ["habitual"]
    assert d["libre"] == pytest.approx(2000 - 128 - 150)  # los restaurantes no se reservan
    assert d["dias"] == 23 and d["libre_por_dia"] == pytest.approx(d["libre"] / 23)


def test_recibo_anual_tras_cobrar_no_se_reserva_dos_veces(db, categoria, movimiento):
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    ibi = categoria("IBI", BudgetGroup.NECESIDAD, recurrente=True, anual=True)
    seguro = categoria("Seguro hogar", BudgetGroup.NECESIDAD, recurrente=True, anual=True)
    for mes in (7, 8):
        movimiento(date(2026, mes, 27), 2858.39, nomina)
    movimiento(date(2026, 9, 28), 2858.39, nomina)  # cobrada: el ciclo ya es el de octubre
    movimiento(date(2025, 10, 5), -346.60, ibi)
    movimiento(date(2025, 10, 15), -200, seguro)  # sin presupuesto: sale de la previsión
    db.add(Budget(category_id=ibi.id, year=2026, month=10, monthly_limit=346.60))
    db.commit()

    d = disponible_service.disponible(db, date(2026, 9, 29))

    assert d["mes_presupuesto"] == (2026, 10)
    assert {f["etiqueta"].split(" · ")[1]: f["pendiente"] for f in d["fijos"]} == pytest.approx(
        {"IBI": 346.60, "Seguro hogar": 200.0}
    )
    assert d["apartado_anual"] == pytest.approx(0.0)  # los de octubre no van también a la hucha
    assert d["anuales"] == []


def test_copiar_un_mes_conserva_lo_decidido_a_mano(db, categoria, movimiento):
    hoy = date.today()
    siguiente = (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)
    cajeros = categoria("Cajeros", BudgetGroup.DESEO)
    regalos = categoria("Regalos", BudgetGroup.DESEO)
    ropa = categoria("Ropa", BudgetGroup.DESEO)
    for dias in (20, 50, 80):  # gasto reciente: el ajuste automático querría añadir Cajeros
        movimiento(hoy - timedelta(days=dias), -400, cajeros)
        movimiento(hoy - timedelta(days=dias), -30, ropa)

    actual = (hoy.year, hoy.month)
    budget_service.upsert_budget(db, cajeros.id, *actual, 250)
    budget_service.upsert_budget(db, regalos.id, *actual, 100, fijado=True)  # sin gasto, pero fijado
    budget_service.upsert_budget(db, ropa.id, *actual, 60)
    quitado = db.query(Budget).filter_by(category_id=cajeros.id).one()
    budget_service.deactivate_budget(db, quitado.id)  # quitado a mano

    assert budget_service.copy_month(db, actual, siguiente) == 2
    budget_service.ajustar_mes(db, *siguiente)

    destino = {b.category_id: b for b in db.query(Budget).filter_by(year=siguiente[0], month=siguiente[1])}
    assert destino[regalos.id].active and destino[regalos.id].fijado
    assert float(destino[regalos.id].monthly_limit) == 100
    assert not destino[cajeros.id].active and destino[cajeros.id].fijado
    assert destino[ropa.id].active and not destino[ropa.id].fijado


def test_dinero_de_paso_no_es_gasto_y_se_ve_su_saldo(db, categoria, movimiento):
    paso = categoria(budget_service.CATEGORIA_DINERO_DE_PASO, BudgetGroup.EXCLUIDO)
    movimiento(date(2026, 10, 1), -180.80, paso, traspaso=True)  # recibo de la inquilina
    movimiento(date(2026, 10, 6), 180, paso, traspaso=True)  # lo devuelve, 0,80 € corto
    movimiento(date(2026, 9, 28), -50, paso, traspaso=True)  # adelantado en septiembre...
    movimiento(date(2026, 10, 2), 50, paso, traspaso=True)  # ...y devuelto en octubre

    assert paso.id not in budget_service.month_expense_by_category(db, 2026, 10)
    octubre = budget_service.dinero_de_paso(db, 2026, 10)
    assert octubre["adelantado"] == pytest.approx(180.80)
    assert octubre["devuelto"] == pytest.approx(230.0)
    assert octubre["saldo"] == pytest.approx(49.20)
    # El mes descuadra por lo de septiembre; el acumulado del año lo compensa.
    assert budget_service.dinero_de_paso(db, 2026, 9)["saldo"] == pytest.approx(-50.0)
    assert octubre["saldo_año"] == pytest.approx(-0.80)
    assert budget_service.dinero_de_paso(db, 2027, 1) is None


def test_enlazar_por_api_no_duplica_lo_importado_a_mano(db, movimiento):
    from app.integrations.enablebanking import sync_service
    from app.models import TransactionSource

    mediolanum = Account(bank=Bank.MEDIOLANUM, name="Mediolanum", external_account_id="uid-1")
    db.add(mediolanum)
    db.commit()
    tx = movimiento(date(2026, 9, 28), 2858.39, en=mediolanum)  # del XLS, con otra descripción
    tx.source = TransactionSource.MANUAL
    db.commit()

    def api(fecha, importe, texto):
        return {"booking_date": fecha, "credit_debit_indicator": "CRDT" if importe > 0 else "DBIT",
                "transaction_amount": {"amount": str(abs(importe)), "currency": "EUR"},
                "remittance_information": [texto]}

    class Respuesta:
        status_code = 200

        def __init__(self, datos):
            self.datos = datos

        def json(self):
            return self.datos

        def raise_for_status(self):
            pass

    class Cliente:
        def get(self, ruta, params=None):
            if ruta.endswith("/balances"):
                return Respuesta({"balances": []})
            return Respuesta({"transactions": [
                api("2026-09-28", 2858.39, "TRANSFERENCIA NOMINA"),
                api("2026-10-28", 2858.39, "TRANSFERENCIA NOMINA"),
            ]})

    r = sync_service.sync_account(db, Cliente(), mediolanum)
    assert (r["inserted"], r["duplicated"]) == (1, 1)


def test_variables_separan_lo_pasado_de_lo_que_sobra(db, categoria, movimiento):
    hoy = date.today()
    super_ = categoria("Súper", BudgetGroup.NECESIDAD)
    bares = categoria("Bares", BudgetGroup.DESEO)
    ropa = categoria("Ropa", BudgetGroup.DESEO)
    venta = categoria("Venta de patrimonio", BudgetGroup.EXCLUIDO)
    for cat, limite in ((super_, 200), (bares, 70), (ropa, 60)):
        budget_service.upsert_budget(db, cat.id, hoy.year, hoy.month, limite)
    # Bares: unos 400 € cada uno de los 6 meses cerrados anteriores.
    inicio = hoy.replace(day=1)
    for i in range(1, 7):
        y, m = divmod(inicio.year * 12 + inicio.month - 1 - i, 12)
        movimiento(date(y, m + 1, 15), -400, bares)
    movimiento(hoy.replace(day=1), -150, super_)
    movimiento(hoy.replace(day=1), -100, bares)
    movimiento(hoy.replace(day=1), -2000, venta)  # excluido: ni presupuesto ni "sin presupuestar"

    v = budget_service.budget_summary(db, hoy.year, hoy.month)
    variables = v["variables"]
    assert [f["categoria"].name for f in variables["pasadas"]] == ["Bares"]
    assert variables["excesos"] == pytest.approx(30)
    assert variables["sobrante"] == pytest.approx(50 + 60)
    # De más a menos gasto; la que no tiene gasto, al final.
    assert [f["categoria"].name for f in variables["filas"]] == ["Súper", "Bares", "Ropa"]
    bares_fila = variables["pasadas"][0]
    assert bares_fila["habitual"] == pytest.approx(400)
    assert bares_fila["poco_realista"] and bares_fila["propuesta"] == 400
    assert not v["sin_presupuesto"]


def test_huchas_arranque_y_traspasos(db, cuenta, movimiento):
    from app.services import huchas_service

    # Recibos: 600 € en el mes 2 y 0 el resto; con 50 €/mes hacen falta 500 € ya.
    hucha = {"meses": [{"total": 0}, {"total": 600}] + [{"total": 0}] * 10}
    assert huchas_service._inicial_recibos(hucha, 50) == pytest.approx(500)

    otra = Account(bank=Bank.ING, name="Préstamos")
    db.add(otra)
    db.commit()
    dia = date(2026, 11, 2)

    def traspaso(importe, en, texto="Traspaso interno emitido"):
        tx = movimiento(dia, importe, en=en, traspaso=True)
        tx.description_normalized = texto.upper()
        db.commit()

    traspaso(-400, cuenta)
    traspaso(400, otra, "Traspaso interno recibido")  # entre cuentas conectadas: no cuenta
    traspaso(-150, cuenta)  # sin pareja: a la Cuenta Naranja
    traspaso(-0.35, cuenta, "Traspaso emitido a Francisco")  # redondeo de ING
    traspaso(-180.8, cuenta, "Recibo Suma gestion tributaria")  # dinero de paso, no es traspaso
    assert huchas_service.traspasado(db, date(2026, 11, 1), date(2026, 11, 30)) == pytest.approx(150.35)


def test_la_averia_la_paga_la_hucha(db, categoria, movimiento):
    hoy = date.today()
    casa = categoria("Mantenimiento del hogar", BudgetGroup.NECESIDAD)
    bares = categoria("Bares", BudgetGroup.DESEO)
    budget_service.upsert_budget(db, casa.id, hoy.year, hoy.month, 10)
    budget_service.upsert_budget(db, bares.id, hoy.year, hoy.month, 70)
    movimiento(hoy.replace(day=1), -460, casa)  # el fontanero
    movimiento(hoy.replace(day=1), -100, bares)

    v = budget_service.budget_summary(db, hoy.year, hoy.month)["variables"]
    assert [f["categoria"].name for f in v["cubiertas"]] == ["Mantenimiento del hogar"]
    assert v["cubierto"] == pytest.approx(450)
    assert [f["categoria"].name for f in v["pasadas"]] == ["Bares"]  # 30 € de más no es una avería
    assert v["excesos"] == pytest.approx(30)


def test_libertad_mira_el_plan_y_no_un_prestamo_ya_pagado(db, cuenta, categoria, movimiento):
    from app.services import libertad_service

    hoy = date.today()
    nomina = categoria("Nómina", BudgetGroup.INGRESO)
    hipoteca = categoria("Hipoteca", BudgetGroup.NECESIDAD, recurrente=True)
    prestamo = categoria("Préstamo", BudgetGroup.NECESIDAD, recurrente=True)
    bares = categoria("Bares", BudgetGroup.DESEO)
    for atras in range(1, 7):  # nómina el día 10 de los seis meses anteriores
        dia = disponible_service._sumar_mes(hoy.replace(day=10), -atras)
        movimiento(dia, 2000, nomina)
        movimiento(dia, -1500, prestamo)  # préstamo liquidado: no está en el presupuesto
        movimiento(dia, -500, hipoteca)
        movimiento(dia, -300, bares)
    db.add_all([
        Budget(category_id=hipoteca.id, year=hoy.year, month=hoy.month, monthly_limit=500),
        Budget(category_id=bares.id, year=hoy.year, month=hoy.month, monthly_limit=200),
        AccountBalance(account_id=cuenta.id, balance=4200, recorded_at=datetime.combine(hoy, datetime.min.time())),
    ])
    cuenta.rol = RolCuenta.AHORRO
    db.commit()

    l = libertad_service.resumen(db, hoy)
    assert l["plan"]["ingresos"] == pytest.approx(2000.0)
    assert l["real"]["tasa_ahorro"] < 0  # los últimos meses, con el préstamo
    assert l["tasa_ahorro"] > 0  # el plan sí cabe
    assert l["colchon"] == pytest.approx(4200.0)  # el ahorro sin asignar es colchón
    assert l["necesidades_medias"] == pytest.approx(500.0)
