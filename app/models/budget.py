from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Budget(Base):
    """Límite de gasto de una categoría hoja para un mes concreto.

    Los presupuestos se preparan por adelantado (p.ej. noviembre desde septiembre) y se copian
    de un mes al siguiente, así que cada fila está anclada a (año, mes) en vez de ser un límite
    mensual permanente: los importes varían de verdad entre meses (la luz, los seguros anuales,
    el IBI...).
    """

    __tablename__ = "budgets"
    __table_args__ = (
        # Deliberadamente sin `active`: quitar y volver a añadir un presupuesto debe reutilizar
        # la fila existente, que es lo que hace el upsert de budget_service.
        UniqueConstraint("category_id", "year", "month", name="uq_budget_categoria_mes"),
        Index("ix_budgets_year_month", "year", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)  # 1-12
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    category: Mapped["Category"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Budget {self.year}-{self.month:02d} "
            f"category_id={self.category_id} limit={self.monthly_limit}>"
        )
