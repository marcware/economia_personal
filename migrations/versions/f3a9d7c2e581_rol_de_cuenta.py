"""rol de cuenta

accounts.rol: el trabajo de cada cuenta (nómina y fondo de emergencia, recibos, día a
día, ahorro), para el cuadre de /dinero y para que el "libre" mire solo las cuentas del
día a día.

Revision ID: f3a9d7c2e581
Revises: e7b1c5d9f224
Create Date: 2026-11-11 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a9d7c2e581'
down_revision: Union[str, Sequence[str], None] = 'e7b1c5d9f224'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("rol", sa.Enum("NOMINA", "RECIBOS", "DIA", "AHORRO", name="rolcuenta"), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("rol")
