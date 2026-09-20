import enum

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BudgetGroup(str, enum.Enum):
    NECESIDAD = "NECESIDAD"
    DESEO = "DESEO"
    AHORRO = "AHORRO"
    INGRESO = "INGRESO"
    EXCLUIDO = "EXCLUIDO"


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), default=None)
    budget_group: Mapped[BudgetGroup | None] = mapped_column(default=None)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)
    is_transfer_category: Mapped[bool] = mapped_column(Boolean, default=False)
    # Distingue "esto lo tengo que pagar sí o sí, mismo importe cada mes" (hipoteca, luz,
    # gimnasio, suscripciones...) de "esto es gasto de comportamiento que puedo recortar
    # este mes" (restaurantes, cajeros, compras...). Es un eje distinto de budget_group:
    # el gimnasio es DESEO (prescindible) pero recurrente (importe fijo todos los meses);
    # el súper es NECESIDAD pero nada recurrente (varía según lo que compres).
    recurrente: Mapped[bool] = mapped_column(Boolean, default=False)
    # Solo tiene sentido si recurrente=True: dentro de los fijos, distingue los que caen
    # repartidos cada mes (hipoteca, luz...) de los que caen en bloque una o dos veces al
    # año (seguros, IBI...). Estos últimos se muestran aparte en /presupuestos con su
    # cifra anual, para que un importe grande en un mes concreto no se lea como un
    # sobrecoste sino como el pago anual que le toca.
    anual: Mapped[bool] = mapped_column(Boolean, default=False)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")

    def __repr__(self) -> str:
        return f"<Category {self.name!r} parent_id={self.parent_id}>"
