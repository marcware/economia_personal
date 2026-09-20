import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GoalType(str, enum.Enum):
    """Tipo de hito. El nombre dice qué se mide y en qué dirección es bueno."""

    GASTO_MAX_CATEGORIA = "GASTO_MAX_CATEGORIA"  # gastar menos de X € en una categoría
    GASTO_MAX_TOTAL = "GASTO_MAX_TOTAL"          # gasto total del mes por debajo de X €
    AHORRO_MIN = "AHORRO_MIN"                    # ahorrar al menos X €
    INVERSION_MIN = "INVERSION_MIN"              # invertir al menos X €
    TASA_AHORRO_MIN = "TASA_AHORRO_MIN"          # tasa de ahorro del mes >= X %


class FinancialGoal(Base):
    """Hito mensual: un objetivo explícito que el mes debe cumplir.

    El estado (cumplido / en riesgo / incumplido) NO se guarda: se recalcula siempre a
    partir de los movimientos reales, igual que los presupuestos.
    """

    __tablename__ = "financial_goals"
    __table_args__ = (
        # Sin UniqueConstraint a propósito: SQLite trata los NULL como distintos, así que
        # (year, month, goal_type, category_id) no deduplicaría justo los cuatro tipos que
        # no llevan categoría. La unicidad se valida en goal_service.upsert_goal().
        Index("ix_financial_goals_year_month", "year", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12
    goal_type: Mapped[GoalType] = mapped_column()
    # Obligatoria en GASTO_MAX_CATEGORIA; opcional en INVERSION_MIN (si es None se cuenta
    # todo el grupo AHORRO). Ignorada en el resto.
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), default=None)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # € o %, según goal_type
    title: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    category: Mapped["Category | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<FinancialGoal {self.year}-{self.month:02d} "
            f"{self.goal_type.value} target={self.target_amount}>"
        )
