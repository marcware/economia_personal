"""plan ing proveedor

El plan de pensiones de ING pasa a leerse de su web (scripts/scrape_ing.py).

Revision ID: a9d2e6f4c831
Revises: f2c5b8d3a617
Create Date: 2026-11-12 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d2e6f4c831'
down_revision: Union[str, Sequence[str], None] = 'f2c5b8d3a617'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

inversiones = sa.table("inversiones", sa.column("nombre", sa.String), sa.column("proveedor", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.nombre == "Plan de pensiones ING").values(proveedor="ing")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(inversiones.update().where(inversiones.c.proveedor == "ing").values(proveedor=None))
