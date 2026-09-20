from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AccountBalance(Base):
    """Fotografía del saldo de una cuenta en un momento dado (de GET /balances)."""

    __tablename__ = "account_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped["Account"] = relationship()  # noqa: F821


class ManualAssetEntry(Base):
    """Valor declarado a mano de un activo que la API no puede ver (inversiones, cripto...).
    Cada actualización inserta una fila nueva; el valor vigente es la más reciente por `name`."""

    __tablename__ = "manual_asset_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ManualLiabilityEntry(Base):
    """Capital pendiente declarado a mano de una deuda (hipoteca, préstamo...).
    Cada actualización inserta una fila nueva; el valor vigente es la más reciente por `name`."""

    __tablename__ = "manual_liability_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    outstanding_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
