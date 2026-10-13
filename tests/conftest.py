"""Base de datos en memoria para los tests: nunca se toca data/economia.db."""

import itertools
import os
import tempfile
from datetime import date

# Antes de importar la app: app.database crea su engine al importarse.
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "tests.db")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (registra todas las tablas)
from app.database import Base  # noqa: E402
from app.models import Account, Bank, BudgetGroup, Category, Transaction  # noqa: E402

_serie = itertools.count(1)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def cuenta(db):
    c = Account(bank=Bank.ING, name="Nómina ING")
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def categoria(db):
    """Crea una categoría hoja (con su padre) de un grupo dado."""

    def _crear(nombre: str, grupo: BudgetGroup, recurrente: bool = False, anual: bool = False) -> Category:
        padre = Category(name=f"Padre {nombre}")
        db.add(padre)
        db.flush()
        hoja = Category(
            name=nombre, parent_id=padre.id, budget_group=grupo, recurrente=recurrente, anual=anual
        )
        db.add(hoja)
        db.commit()
        return hoja

    return _crear


@pytest.fixture
def movimiento(db, cuenta):
    def _crear(fecha: date, importe: float, cat: Category | None = None, *, en: Account | None = None,
               traspaso: bool = False) -> Transaction:
        n = next(_serie)
        tx = Transaction(
            account_id=(en or cuenta).id, date=fecha, amount=importe,
            description_raw=f"mov {n}", description_normalized=f"MOV {n}",
            category_id=cat.id if cat else None, is_transfer=traspaso, fingerprint=f"test-{n}",
        )
        db.add(tx)
        db.commit()
        return tx

    return _crear
