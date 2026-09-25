"""activo liquido

Añade manual_asset_entries.liquido: separa el colchón (dinero disponible en días) de la
inversión a largo plazo, para calcular los meses de fondo de emergencia en /patrimonio.
Marca como líquidos los activos ya declarados que son colchón o cuenta de ahorro.

Revision ID: d8a1f6c3e5b2
Revises: c5e2a4b91f0d
Create Date: 2026-09-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8a1f6c3e5b2'
down_revision: Union[str, Sequence[str], None] = 'c5e2a4b91f0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Activos ya declarados que son dinero disponible, por fragmento de nombre.
LIQUIDOS = ["%colchón%", "%Cuenta Naranja%"]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "manual_asset_entries",
        sa.Column("liquido", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    activos = sa.table("manual_asset_entries", sa.column("name", sa.String), sa.column("liquido", sa.Boolean))
    conn = op.get_bind()
    for patron in LIQUIDOS:
        conn.execute(activos.update().where(activos.c.name.like(patron)).values(liquido=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("manual_asset_entries", "liquido")
