"""La aritmética de dinero que más duele si se rompe: gasto neto, qué es ingreso, ciclo de
nómina, el "libre" de la portada y la copia de presupuestos."""

from datetime import date, datetime, timedelta

import pytest

from app.categorization.seed_rules import CATEGORY_TREE
from app.models import Account, AccountBalance, Bank, Budget, BudgetGroup
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
    movimiento(date(2026, 9, 28), 3000, nomina)
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
