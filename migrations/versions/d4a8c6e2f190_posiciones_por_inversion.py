"""posiciones por inversion

cripto_posiciones pasa a posiciones, con inversion_id y nombre del activo, para que Bit2Me
y Trade Republic guarden sus fotos en la misma tabla sin mezclarse.

Revision ID: d4a8c6e2f190
Revises: b3f7d1e9a524
Create Date: 2026-11-12 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4a8c6e2f190'
down_revision: Union[str, Sequence[str], None] = 'b3f7d1e9a524'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("cripto_posiciones", "posiciones")
    with op.batch_alter_table("posiciones") as batch:
        batch.add_column(sa.Column("inversion_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("nombre", sa.String(100), nullable=True))
    # Hasta ahora todas las fotos eran de Bit2Me.
    op.execute("UPDATE posiciones SET inversion_id = (SELECT id FROM inversiones WHERE proveedor = 'bit2me')")
    op.execute("DELETE FROM posiciones WHERE inversion_id IS NULL")
    with op.batch_alter_table("posiciones") as batch:
        batch.alter_column("inversion_id", nullable=False)
        batch.create_foreign_key("fk_posiciones_inversion", "inversiones", ["inversion_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM posiciones WHERE inversion_id <> (SELECT id FROM inversiones WHERE proveedor = 'bit2me')")
    with op.batch_alter_table("posiciones") as batch:
        batch.drop_constraint("fk_posiciones_inversion", type_="foreignkey")
        batch.drop_column("nombre")
        batch.drop_column("inversion_id")
    op.rename_table("posiciones", "cripto_posiciones")
