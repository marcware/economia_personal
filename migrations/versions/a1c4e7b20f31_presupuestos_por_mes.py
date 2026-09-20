"""presupuestos por mes

Añade (year, month) a budgets para poder preparar el presupuesto de un mes concreto
por adelantado, en vez de tener un único límite permanente por categoría.

La tabla estaba vacía cuando se escribió esta migración, así que se recrea con
batch_alter_table sin conservar datos: SQLite no admite ADD COLUMN NOT NULL sin default.

Revision ID: a1c4e7b20f31
Revises: f3918b39549d
Create Date: 2026-09-19 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e7b20f31'
down_revision: Union[str, Sequence[str], None] = 'f3918b39549d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("budgets", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("year", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("month", sa.Integer(), nullable=False))
        batch_op.create_unique_constraint(
            "uq_budget_categoria_mes", ["category_id", "year", "month"]
        )
    op.create_index("ix_budgets_year_month", "budgets", ["year", "month"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_budgets_year_month", table_name="budgets")
    with op.batch_alter_table("budgets", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_budget_categoria_mes", type_="unique")
        batch_op.drop_column("month")
        batch_op.drop_column("year")
