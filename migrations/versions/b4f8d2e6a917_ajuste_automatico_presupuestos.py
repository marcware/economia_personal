"""ajuste automatico de presupuestos

- budgets.fijado: el usuario ha decidido a mano sobre ese presupuesto; el ajuste
  automático (budget_service.ajustar_mes) no lo toca. Los presupuestos ya quitados
  (active=0) los quitó el usuario, así que nacen fijados para no volver a añadirlos.
- budgets.ajuste_auto: "añadido"/"quitado" si la última alta o baja fue automática.

Revision ID: b4f8d2e6a917
Revises: a9e3c1f7d240
Create Date: 2026-09-25 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4f8d2e6a917'
down_revision: Union[str, Sequence[str], None] = 'a9e3c1f7d240'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("budgets", sa.Column("fijado", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("budgets", sa.Column("ajuste_auto", sa.String(10), nullable=True))
    op.execute("UPDATE budgets SET fijado = 1 WHERE active = 0")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("budgets") as batch:
        batch.drop_column("ajuste_auto")
        batch.drop_column("fijado")
