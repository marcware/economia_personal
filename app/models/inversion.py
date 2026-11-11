from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Inversion(Base):
    """Una inversión con contabilidad propia, independiente de los movimientos del banco:
    lo aportado son sus `Aportacion` y el valor, la última ManualAssetEntry con su `nombre`
    (así /patrimonio la suma sin saber nada de inversiones).

    proveedor: "bit2me" si su valor y sus aportaciones llegan por API; None si se apuntan a mano.
    category_id: la subcategoría de "Inversión" del banco a la que van sus transferencias. No
    se usa para calcular nada aquí; sirve para comparar después con lo que ha salido del banco.
    """

    __tablename__ = "inversiones"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    proveedor: Mapped[str | None] = mapped_column(String(20), default=None)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), default=None)


class Aportacion(Base):
    """Dinero que entra (+) o sale (−) de una inversión desde fuera de ella, en euros. Las de
    Bit2Me vienen de su API (external_id = id de la operación, para no duplicar); las demás
    se apuntan a mano. Los movimientos internos (comprar una cripto con el saldo en euros,
    pasar a Earn) no son aportaciones."""

    __tablename__ = "aportaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    inversion_id: Mapped[int] = mapped_column(ForeignKey("inversiones.id"))
    fecha: Mapped[date] = mapped_column(Date)
    importe: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    nota: Mapped[str | None] = mapped_column(String(200), default=None)
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CriptoPosicion(Base):
    """Foto de una moneda en Bit2Me al sincronizar: cantidad (wallet + Earn + Pro) y su
    valor en euros en ese momento. Todas las filas de una sincronización comparten
    `recorded_at`; el total se guarda además como ManualAssetEntry("Bit2Me"), que es lo que
    leen /inversiones y /patrimonio."""

    __tablename__ = "cripto_posiciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    precio_eur: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    valor_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # De bit2me/cartera.py: lo que costó lo que queda (FIFO), lo ganado/perdido en ventas ya
    # hechas y la cantidad que vino de recompensas de Earn (a coste cero).
    coste_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    realizado_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    recompensas: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), default=None)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
