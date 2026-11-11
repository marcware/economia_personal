"""pias proveedor

El PIAS de Mediolanum pasa a leerse de su banca online (scripts/scrape_mediolanum.py).

Revision ID: f2c5b8d3a617
Revises: d4a8c6e2f190
Create Date: 2026-11-12 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2c5b8d3a617'
down_revision: Union[str, Sequence[str], None] = 'd4a8c6e2f190'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

inversiones = sa.table("inversiones", sa.column("nombre", sa.String), sa.column("proveedor", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.nombre == "PIAS Mediolanum").values(proveedor="mediolanum")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.proveedor == "mediolanum").values(proveedor=None)
    )
