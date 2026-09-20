import enum
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Bank(str, enum.Enum):
    ING = "ING"
    MEDIOLANUM = "MEDIOLANUM"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank: Mapped[Bank]
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    # "uid" de Enable Banking: solo válido mientras la sesión que lo generó esté AUTHORIZED,
    # se sobreescribe en cada reconexión. identification_hash es el identificador estable.
    external_account_id: Mapped[str | None] = mapped_column(String(100), default=None)
    iban: Mapped[str | None] = mapped_column(String(34), default=None)
    identification_hash: Mapped[str | None] = mapped_column(String(100), default=None, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<Account {self.name!r} ({self.bank})>"
