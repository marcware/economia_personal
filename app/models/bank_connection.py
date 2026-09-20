import enum
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConnectionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BankConnection(Base):
    __tablename__ = "bank_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    aspsp_name: Mapped[str] = mapped_column(String(100))
    aspsp_country: Mapped[str] = mapped_column(String(2))
    session_id: Mapped[str | None] = mapped_column(String(200), default=None)
    consent_valid_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[ConnectionStatus] = mapped_column(default=ConnectionStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<BankConnection {self.aspsp_name!r} status={self.status}>"
