import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TransferCandidateStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class TransferCandidate(Base):
    """Posible traspaso entre cuentas propias detectado automáticamente (importe opuesto,
    fecha cercana, cuentas distintas) pendiente de confirmar o rechazar a mano."""

    __tablename__ = "transfer_candidates"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_transfer_candidate_transaction"),
        UniqueConstraint("matched_transaction_id", name="uq_transfer_candidate_matched"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    matched_transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    days_apart: Mapped[int] = mapped_column(Integer)
    status: Mapped[TransferCandidateStatus] = mapped_column(default=TransferCandidateStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(foreign_keys=[transaction_id])  # noqa: F821
    matched_transaction: Mapped["Transaction"] = relationship(foreign_keys=[matched_transaction_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<TransferCandidate {self.transaction_id}<->{self.matched_transaction_id} {self.status}>"
