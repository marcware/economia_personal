import enum
from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AmountSign(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    ANY = "ANY"


class CategorizationRule(Base):
    __tablename__ = "categorization_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200))
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    amount_sign: Mapped[AmountSign] = mapped_column(default=AmountSign.ANY)
    # Importe mínimo (en valor absoluto) para que la regla aplique. Sirve cuando la misma
    # descripción mezcla cosas distintas según el importe: la inquilina paga el alquiler
    # (400 €) y devuelve recibos (30 €) con la misma transferencia.
    min_abs_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_from_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    category: Mapped["Category"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return f"<CategorizationRule pattern={self.pattern!r} category_id={self.category_id}>"
