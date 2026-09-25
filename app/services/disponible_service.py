"""Disponible hasta la próxima nómina: cuánto dinero de la cuenta es de verdad libre hoy.

Responde a "¿me puedo permitir esto?" mirando la caja real, no el mes natural: la
nómina entra hacia el día 27, así que el dinero de octubre llega en septiembre y los
fijos gordos (hipoteca el día 1, préstamos el 3, luz hacia el 10) caen después de
cobrar. Ver solo "lo que llevo gastado este mes" engaña justo en esos días: la cuenta
está llena pero buena parte ya tiene dueño.

    libre = saldo en cuentas
            - fijos que faltan por cobrarse antes de la próxima nómina
            - inversión comprometida que falta por hacer
            - necesidades variables que aún faltan (súper, gasolina, farmacia...)
            - apartado para gastos anuales (seguros, impuestos...)

Es la idea de "Safe to Spend" (Rocket Money) / "In My Pocket" (PocketGuard) y de las
"true expenses" de YNAB, calculada con los presupuestos del mes si existen y, si no,
con la mediana real de los últimos meses.

El ciclo se asigna al mes de presupuesto en el que termina (27 sep -> 26 oct es
octubre): la nómina de finales de mes paga el mes siguiente.
"""

import calendar
import statistics
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Account, AccountBalance, Bank, Budget, BudgetGroup, Category, Transaction
from app.services import budget_service
from app.services.dashboard_service import MONTHS_ES

# Meses naturales cerrados que se usan para estimar un gasto cuando no hay presupuesto.
MESES_HISTORICO = 3

# Una nómina es un ingreso de la categoría de nómina de al menos esta fracción de la
# mediana de esa categoría (evita tomar por nómina un abono pequeño en la misma categoría).
FRACCION_NOMINA = 0.5

# A partir de estos días sin sincronizar, el saldo se marca como poco fiable.
DIAS_SALDO_VIEJO = 3


def _sumar_mes(d: date, meses: int = 1) -> date:
    y, m = divmod(d.month - 1 + meses, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _categoria_nomina(db: Session, hoy: date) -> int | None:
    """La categoría de ingreso que más dinero ha traído en los últimos 6 meses."""
    fila = (
        db.query(Transaction.category_id, func.sum(Transaction.amount).label("total"))
        .join(Category, Category.id == Transaction.category_id)
        .filter(
            Category.budget_group == BudgetGroup.INGRESO,
            Transaction.amount > 0,
            Transaction.is_transfer.is_(False),
            Transaction.date >= _sumar_mes(hoy, -6),
        )
        .group_by(Transaction.category_id)
        .order_by(func.sum(Transaction.amount).desc())
        .first()
    )
    return fila.category_id if fila else None


def ciclo_nomina(db: Session, hoy: date | None = None) -> dict:
    """Última nómina cobrada y fecha prevista de la siguiente.

    Sin nómina detectable, el ciclo cae al mes natural en curso.
    """
    hoy = hoy or date.today()
    cid = _categoria_nomina(db, hoy)
    nominas = []
    if cid is not None:
        nominas = (
            db.query(Transaction.date, Transaction.amount)
            .filter(Transaction.category_id == cid, Transaction.amount > 0, Transaction.date <= hoy)
            .order_by(Transaction.date.desc())
            .limit(12)
            .all()
        )
    if nominas:
        mediana = statistics.median(float(n.amount) for n in nominas)
        nominas = [n for n in nominas if float(n.amount) >= FRACCION_NOMINA * mediana]

    if not nominas:
        inicio = hoy.replace(day=1)
        siguiente = _sumar_mes(inicio)
        return {
            "inicio": inicio, "siguiente": siguiente, "detectada": False,
            "importe_nomina": None, "retrasada": False,
        }

    ultima = nominas[0]
    siguiente = _sumar_mes(ultima.date)
    return {
        "inicio": ultima.date,
        "siguiente": siguiente,
        "detectada": True,
        "importe_nomina": float(ultima.amount),
        # La nómina tocaba y no ha llegado (fin de semana, festivo...): el ciclo sigue
        # siendo el anterior, pero se avisa para no leer "0 días" como "ya he cobrado".
        "retrasada": siguiente <= hoy,
    }


def _saldo_cuentas(db: Session) -> tuple[float, date | None]:
    """Suma del último saldo conocido de cada cuenta sincronizada por API.

    Mediolanum queda fuera: su saldo es el colchón, se declara a mano en /patrimonio y
    no es dinero para el día a día.
    """
    total, mas_antiguo = 0.0, None
    for cuenta in db.query(Account).filter(Account.bank != Bank.MEDIOLANUM).all():
        saldo = (
            db.query(AccountBalance)
            .filter_by(account_id=cuenta.id)
            .order_by(AccountBalance.recorded_at.desc())
            .first()
        )
        if saldo is None:
            continue
        total += float(saldo.balance)
        fecha = saldo.recorded_at.date()
        mas_antiguo = fecha if mas_antiguo is None else min(mas_antiguo, fecha)
    return total, mas_antiguo


def _gastado_por_categoria(db: Session, desde: date, hasta: date) -> dict[int, float]:
    filas = (
        db.query(Transaction.category_id, func.sum(Transaction.amount))
        .filter(
            Transaction.amount < 0,
            Transaction.is_transfer.is_(False),
            Transaction.category_id.isnot(None),
            Transaction.date >= desde,
            Transaction.date <= hasta,
        )
        .group_by(Transaction.category_id)
        .all()
    )
    return {cid: -float(total) for cid, total in filas}


def _mediana_mensual(db: Session, category_id: int, year: int, month: int) -> float:
    """Mediana del gasto de una categoría en los MESES_HISTORICO meses naturales previos
    a (year, month), contando como 0 los meses sin gasto."""
    importes = []
    cursor = date(year, month, 1)
    for _ in range(MESES_HISTORICO):
        cursor = _sumar_mes(cursor, -1)
        fin = _sumar_mes(cursor) - timedelta(days=1)
        importes.append(
            _gastado_por_categoria(db, cursor, fin).get(category_id, 0.0)
        )
    return statistics.median(importes) if importes else 0.0


def disponible(db: Session, hoy: date | None = None) -> dict:
    """Desglose de lo que es libre hoy hasta la próxima nómina. Ver docstring del módulo."""
    hoy = hoy or date.today()
    ciclo = ciclo_nomina(db, hoy)
    fin_ciclo = ciclo["siguiente"] - timedelta(days=1)
    year, month = fin_ciclo.year, fin_ciclo.month

    saldo, fecha_saldo = _saldo_cuentas(db)
    gastado = _gastado_por_categoria(db, ciclo["inicio"], hoy)
    presupuestos = {
        b.category_id: float(b.monthly_limit)
        for b in db.query(Budget).filter_by(active=True, year=year, month=month).all()
    }

    fijos, variables_necesarios = [], []
    anuales_presupuestadas = set()
    for cat in db.query(Category).filter(Category.parent_id.isnot(None)).all():
        if cat.is_transfer_category or cat.budget_group in (
            BudgetGroup.AHORRO, BudgetGroup.INGRESO, BudgetGroup.EXCLUIDO, None
        ):
            continue
        if cat.anual:
            # Los anuales solo cuentan como pago pendiente si están presupuestados en
            # este mes (su mes de vencimiento); si no, van al apartado anual de abajo.
            if cat.id not in presupuestos:
                continue
            anuales_presupuestadas.add(cat.id)
        elif not cat.recurrente and cat.budget_group != BudgetGroup.NECESIDAD:
            continue  # deseos variables: es precisamente lo que el "libre" deja decidir

        if cat.id in presupuestos:
            previsto, origen = presupuestos[cat.id], "presupuesto"
        else:
            previsto, origen = _mediana_mensual(db, cat.id, year, month), "media"
        ya = gastado.get(cat.id, 0.0)
        pendiente = max(previsto - ya, 0.0)
        if previsto <= 0 and ya <= 0:
            continue
        fila = {
            "etiqueta": f"{cat.parent.name} · {cat.name}",
            "previsto": previsto,
            "gastado": ya,
            "pendiente": pendiente,
            "origen": origen,
        }
        (fijos if cat.recurrente else variables_necesarios).append(fila)

    fijos.sort(key=lambda f: -f["pendiente"])
    variables_necesarios.sort(key=lambda f: -f["pendiente"])

    inversion_prevista = budget_service.inversion_esperada(db, year, month)
    ids_ahorro = {
        c.id for c in db.query(Category).filter(Category.budget_group == BudgetGroup.AHORRO).all()
    }
    inversion_hecha = sum(v for cid, v in gastado.items() if cid in ids_ahorro)
    inversion_pendiente = max(inversion_prevista - inversion_hecha, 0.0)

    apartado_anual = 0.0
    anuales = []
    for g in budget_service.gastos_anuales(db, hoy.year):
        if g["categoria"].id in anuales_presupuestadas or not g["por_mes_restante"]:
            continue
        apartado_anual += g["por_mes_restante"]
        anuales.append({"etiqueta": g["etiqueta"], "importe": g["por_mes_restante"]})

    total_fijos = sum(f["pendiente"] for f in fijos)
    total_variables = sum(f["pendiente"] for f in variables_necesarios)
    comprometido = total_fijos + total_variables + inversion_pendiente + apartado_anual
    libre = saldo - comprometido
    dias = max((ciclo["siguiente"] - hoy).days, 1)

    return {
        "hoy": hoy,
        "ciclo": ciclo,
        "mes_presupuesto": (year, month),
        "mes_presupuesto_nombre": f"{MONTHS_ES[month]} {year}",
        "con_presupuesto": bool(presupuestos),
        "saldo": saldo,
        "fecha_saldo": fecha_saldo,
        "saldo_viejo": fecha_saldo is not None and (hoy - fecha_saldo).days > DIAS_SALDO_VIEJO,
        "fijos": fijos,
        "total_fijos": total_fijos,
        "variables_necesarios": variables_necesarios,
        "total_variables": total_variables,
        "inversion_prevista": inversion_prevista,
        "inversion_hecha": inversion_hecha,
        "inversion_pendiente": inversion_pendiente,
        "anuales": anuales,
        "apartado_anual": apartado_anual,
        "comprometido": comprometido,
        "libre": libre,
        "dias": dias,
        "libre_por_dia": libre / dias,
    }
