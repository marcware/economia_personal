"""venta de patrimonio

Subcategoría nueva Movimientos excluidos · Venta de patrimonio y cancelación de deuda
(EXCLUIDO): vender un bien y cancelar préstamos con lo cobrado no es ingreso, gasto ni
ahorro del mes. Sin reglas: los movimientos se clasifican a mano.

Revision ID: e8c3a5f1d204
Revises: d2f6b8a4c917
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8c3a5f1d204'
down_revision: Union[str, Sequence[str], None] = 'd2f6b8a4c917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUEVA = ("Movimientos excluidos", "Venta de patrimonio y cancelación de deuda", "EXCLUIDO")  # debe coincidir con CATEGORY_TREE

categorias = sa.table(
    "categories",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("parent_id", sa.Integer),
    sa.column("budget_group", sa.String),
    sa.column("is_system", sa.Boolean),
    sa.column("is_transfer_category", sa.Boolean),
    sa.column("recurrente", sa.Boolean),
    sa.column("anual", sa.Boolean),
)
movimientos = sa.table(
    "transactions",
    sa.column("id", sa.Integer),
    sa.column("category_id", sa.Integer),
)


def _id(conn) -> int | None:
    padre = categorias.alias("padre")
    return conn.execute(
        sa.select(categorias.c.id)
        .select_from(categorias.join(padre, categorias.c.parent_id == padre.c.id))
        .where(padre.c.name == NUEVA[0], categorias.c.name == NUEVA[1])
    ).scalar()


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    padre, nombre, grupo = NUEVA
    if _id(conn) is not None:
        return
    parent_id = conn.execute(
        sa.select(categorias.c.id).where(categorias.c.parent_id.is_(None), categorias.c.name == padre)
    ).scalar()
    if parent_id is not None:
        conn.execute(categorias.insert().values(
            name=nombre, parent_id=parent_id, budget_group=grupo, is_system=True,
            is_transfer_category=False, recurrente=False, anual=False,
        ))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    cid = _id(conn)
    if cid is None:
        return
    usada = conn.execute(sa.select(movimientos.c.id).where(movimientos.c.category_id == cid).limit(1)).first()
    if usada is None:
        conn.execute(categorias.delete().where(categorias.c.id == cid))
