"""categoria anual

Añade categories.anual: dentro de los gastos fijos (recurrente=True), distingue los
que caen repartidos cada mes (hipoteca, luz...) de los que caen en bloque una o dos
veces al año (seguros, IBI). Alimenta la sección "Gastos anuales" de /presupuestos,
para que un importe grande en un mes concreto se lea como el pago anual que le toca,
no como un sobrecoste de ese mes.

Revision ID: c5e2a4b91f0d
Revises: b7d3f9a1c802
Create Date: 2026-09-20 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e2a4b91f0d'
down_revision: Union[str, Sequence[str], None] = 'b7d3f9a1c802'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (categoría padre, subcategoría) marcadas como anuales. Debe coincidir con
# CATEGORY_TREE en app/categorization/seed_rules.py.
ANUALES = [
    ("Otros gastos", "Pago de impuestos"),
    ("Otros gastos", "Seguros"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "categories", sa.Column("anual", sa.Boolean(), nullable=False, server_default=sa.text("0"))
    )
    conn = op.get_bind()
    categorias = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("parent_id", sa.Integer),
        sa.column("anual", sa.Boolean),
    )
    padres = {
        row.name: row.id
        for row in conn.execute(sa.select(categorias.c.id, categorias.c.name).where(categorias.c.parent_id.is_(None)))
    }
    for parent_name, sub_name in ANUALES:
        parent_id = padres.get(parent_name)
        if parent_id is None:
            continue
        conn.execute(
            categorias.update()
            .where(categorias.c.parent_id == parent_id, categorias.c.name == sub_name)
            .values(anual=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categories", "anual")
