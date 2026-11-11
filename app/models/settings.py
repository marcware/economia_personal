from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserSettings(Base):
    """Fila única (id=1) con la configuración del coach financiero."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    needs_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("50"))
    wants_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("30"))
    savings_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20"))
    anomaly_stddev_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("1.5"))
    # Cuota mensual de la hucha de viajes e imprevistos, la decide el usuario (ver
    # huchas_service). None = la que se sugiere del histórico.
    hucha_variable: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
