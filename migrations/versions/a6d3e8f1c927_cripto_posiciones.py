"""cripto posiciones

Foto por moneda de cada sincronización de Bit2Me (cantidad, precio y valor en euros).

Revision ID: a6d3e8f1c927
Revises: f4a7c2e9b815
Create Date: 2026-11-11 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6d3e8f1c927'
down_revision: Union[str, Sequence[str], None] = 'f4a7c2e9b815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "cripto_posiciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("cantidad", sa.Numeric(30, 12), nullable=False),
        sa.Column("precio_eur", sa.Numeric(20, 8), nullable=False),
        sa.Column("valor_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("cripto_posiciones")
