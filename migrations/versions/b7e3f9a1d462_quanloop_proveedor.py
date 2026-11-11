"""quanloop proveedor

Quanloop pasa a leerse de su web (scripts/scrape_quanloop.py).

Revision ID: b7e3f9a1d462
Revises: a9d2e6f4c831
Create Date: 2026-11-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3f9a1d462'
down_revision: Union[str, Sequence[str], None] = 'a9d2e6f4c831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

inversiones = sa.table("inversiones", sa.column("nombre", sa.String), sa.column("proveedor", sa.String))


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().execute(
        inversiones.update().where(inversiones.c.nombre == "Quanloop").values(proveedor="quanloop")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(inversiones.update().where(inversiones.c.proveedor == "quanloop").values(proveedor=None))
