"""alquiler cobrado y dinero de paso

- categorization_rules.min_abs_amount: importe mínimo opcional para que una regla
  aplique (el alquiler y las devoluciones de recibos de la inquilina llegan con la
  misma descripción y solo se distinguen por el importe).
- Categorías "Otros ingresos · Alquiler cobrado" (INGRESO) y "Movimientos excluidos ·
  Dinero de paso (botes)" (excluida, como un traspaso), si no existen ya.

Revision ID: e2b7c4d9a613
Revises: d8a1f6c3e5b2
Create Date: 2026-09-25 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2b7c4d9a613'
down_revision: Union[str, Sequence[str], None] = 'd8a1f6c3e5b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (padre, subcategoría, budget_group, is_transfer_category). Debe coincidir con
# CATEGORY_TREE en app/categorization/seed_rules.py.
NUEVAS = [
    ("Otros ingresos", "Alquiler cobrado", "INGRESO", False),
    ("Movimientos excluidos", "Dinero de paso (botes)", "EXCLUIDO", True),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("categorization_rules", sa.Column("min_abs_amount", sa.Numeric(12, 2), nullable=True))

    conn = op.get_bind()
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
    padres = {
        row.name: row.id
        for row in conn.execute(sa.select(categorias.c.id, categorias.c.name).where(categorias.c.parent_id.is_(None)))
    }
    for padre, nombre, grupo, es_traspaso in NUEVAS:
        parent_id = padres.get(padre)
        if parent_id is None:
            continue
        existe = conn.execute(
            sa.select(categorias.c.id).where(categorias.c.parent_id == parent_id, categorias.c.name == nombre)
        ).first()
        if existe is None:
            conn.execute(categorias.insert().values(
                name=nombre, parent_id=parent_id, budget_group=grupo, is_system=True,
                is_transfer_category=es_traspaso, recurrente=False, anual=False,
            ))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categorization_rules", "min_abs_amount")
