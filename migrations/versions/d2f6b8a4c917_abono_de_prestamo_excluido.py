"""abono de prestamo excluido

Un préstamo abonado en cuenta no es ingreso ni una devolución de gasto:
- Otros ingresos · Abono de financiación pasa de INGRESO a EXCLUIDO.
- La regla "ABONO DE PRESTAMO" y sus movimientos salen de Otros préstamos y avales (NECESIDAD,
  donde el abono restaba de las cuotas como si fuera una devolución) hacia ella.

Revision ID: d2f6b8a4c917
Revises: c7a2e9d4b153
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f6b8a4c917'
down_revision: Union[str, Sequence[str], None] = 'c7a2e9d4b153'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PATRON = "ABONO DE PRESTAMO"
CUOTAS = ("Otros gastos", "Otros préstamos y avales")
ABONO = ("Otros ingresos", "Abono de financiación")  # debe coincidir con CATEGORY_TREE

categorias = sa.table(
    "categories",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("parent_id", sa.Integer),
    sa.column("budget_group", sa.String),
)
reglas = sa.table(
    "categorization_rules",
    sa.column("id", sa.Integer),
    sa.column("pattern", sa.String),
    sa.column("category_id", sa.Integer),
)
movimientos = sa.table(
    "transactions",
    sa.column("id", sa.Integer),
    sa.column("description_normalized", sa.Text),
    sa.column("category_id", sa.Integer),
    sa.column("manually_categorized", sa.Boolean),
)


def _hojas(conn) -> dict[tuple[str, str], int]:
    padre = categorias.alias("padre")
    filas = conn.execute(
        sa.select(categorias.c.id, padre.c.name, categorias.c.name)
        .select_from(categorias.join(padre, categorias.c.parent_id == padre.c.id))
    )
    return {(p, h): cid for cid, p, h in filas}


def _mover(conn, desde: int, hacia: int) -> None:
    conn.execute(reglas.update().where(reglas.c.pattern == PATRON, reglas.c.category_id == desde)
                 .values(category_id=hacia))
    conn.execute(
        movimientos.update()
        .where(
            movimientos.c.category_id == desde,
            movimientos.c.manually_categorized.is_(False),
            movimientos.c.description_normalized.contains(PATRON, autoescape=True),
        )
        .values(category_id=hacia)
    )


def _aplicar(grupo: str, hacia_abono: bool) -> None:
    conn = op.get_bind()
    hojas = _hojas(conn)
    cuotas, abono = hojas.get(CUOTAS), hojas.get(ABONO)
    if abono is None:
        return
    conn.execute(categorias.update().where(categorias.c.id == abono).values(budget_group=grupo))
    if cuotas is not None:
        _mover(conn, *((cuotas, abono) if hacia_abono else (abono, cuotas)))


def upgrade() -> None:
    """Upgrade schema."""
    _aplicar("EXCLUIDO", hacia_abono=True)


def downgrade() -> None:
    """Downgrade schema."""
    _aplicar("INGRESO", hacia_abono=False)
