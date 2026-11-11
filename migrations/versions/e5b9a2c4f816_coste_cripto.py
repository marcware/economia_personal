"""coste cripto

Coste (FIFO), resultado realizado y recompensas de Earn en cada foto de Bit2Me.

Revision ID: e5b9a2c4f816
Revises: c8e1f5a3d702
Create Date: 2026-11-11 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b9a2c4f816'
down_revision: Union[str, Sequence[str], None] = 'c8e1f5a3d702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = (("coste_eur", sa.Numeric(12, 2)), ("realizado_eur", sa.Numeric(12, 2)), ("recompensas", sa.Numeric(30, 12)))


def upgrade() -> None:
    """Upgrade schema."""
    for nombre, tipo in COLUMNAS:
        op.add_column("cripto_posiciones", sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("cripto_posiciones") as batch:
        for nombre, _ in COLUMNAS:
            batch.drop_column(nombre)
