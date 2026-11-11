"""trade republic proveedor

Trade Republic pasa a leerse por su API (pytr): su inversión se marca con proveedor.

Revision ID: b3f7d1e9a524
Revises: e5b9a2c4f816
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7d1e9a524'
down_revision: Union[str, Sequence[str], None] = 'e5b9a2c4f816'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

inversiones = sa.table("inversiones", sa.column("nombre", sa.String), sa.column("proveedor", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.nombre == "Trade Republic").values(proveedor="traderepublic")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.proveedor == "traderepublic").values(proveedor=None)
    )
