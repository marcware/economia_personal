"""categoria recurrente

Añade categories.recurrente: distingue gastos fijos (mismo importe todos los meses,
un compromiso ya adquirido) de gastos variables/de comportamiento (donde tiene sentido
intentar recortar). Es un eje distinto de budget_group: el gimnasio es DESEO pero
recurrente; el súper es NECESIDAD pero nada recurrente.

Se rellena por nombre de categoría porque la tabla ya tiene filas (a diferencia de
budgets/financial_goals, que nacieron vacías).

Revision ID: b7d3f9a1c802
Revises: fef0f2c8414f
Create Date: 2026-09-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3f9a1c802'
down_revision: Union[str, Sequence[str], None] = 'fef0f2c8414f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (categoría padre, subcategoría) marcadas como recurrentes. Debe coincidir con
# CATEGORY_TREE en app/categorization/seed_rules.py.
RECURRENTES = [
    ("Ahorro", "Redondeo"),
    ("Educación y salud", "Deporte y gimnasio"),
    ("Hogar", "Alquiler vivienda"),
    ("Hogar", "Hipoteca"),
    ("Hogar", "Luz y gas"),
    ("Hogar", "Teléfono, TV e internet"),
    ("Inversión", "Otras inversiones"),
    ("Otros gastos", "Otros préstamos y avales"),
    ("Otros gastos", "Pago de impuestos"),
    ("Otros gastos", "Seguros"),
    ("Otros gastos", "Suscripciones"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "categories", sa.Column("recurrente", sa.Boolean(), nullable=False, server_default=sa.text("0"))
    )
    conn = op.get_bind()
    categorias = sa.table(
        "categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("parent_id", sa.Integer),
        sa.column("recurrente", sa.Boolean),
    )
    padres = {
        row.name: row.id
        for row in conn.execute(sa.select(categorias.c.id, categorias.c.name).where(categorias.c.parent_id.is_(None)))
    }
    for parent_name, sub_name in RECURRENTES:
        parent_id = padres.get(parent_name)
        if parent_id is None:
            continue
        conn.execute(
            categorias.update()
            .where(categorias.c.parent_id == parent_id, categorias.c.name == sub_name)
            .values(recurrente=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categories", "recurrente")
