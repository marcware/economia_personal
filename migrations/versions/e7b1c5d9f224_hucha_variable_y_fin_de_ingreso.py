"""hucha variable y fin de ingreso

- user_settings.hucha_variable: cuota mensual que el usuario decide para la hucha de viajes
  e imprevistos (la de recibos anuales se calcula sola).
- categories.fin_ingreso: último día en que se cobra un ingreso que se acaba (el alquiler
  de una vivienda vendida), para no contarlo como previsto en los meses siguientes.

Revision ID: e7b1c5d9f224
Revises: c4e8a2f6b913
Create Date: 2026-11-11 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b1c5d9f224'
down_revision: Union[str, Sequence[str], None] = 'c4e8a2f6b913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("user_settings") as batch:
        batch.add_column(sa.Column("hucha_variable", sa.Numeric(10, 2), nullable=True))
    with op.batch_alter_table("categories") as batch:
        batch.add_column(sa.Column("fin_ingreso", sa.Date(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("categories") as batch:
        batch.drop_column("fin_ingreso")
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("hucha_variable")
