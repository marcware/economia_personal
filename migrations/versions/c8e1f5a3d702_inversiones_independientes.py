"""inversiones independientes

Las inversiones dejan de calcularse con los movimientos del banco: `inversiones` pasa a ser
la entidad (nombre, proveedor, subcategoría del banco solo como referencia) y lo aportado se
lleva en `aportaciones` (de la API de Bit2Me o a mano). Se crea una inversión por cada
subcategoría de "Inversión" que tenga un valor declarado o movimientos.

Revision ID: c8e1f5a3d702
Revises: a6d3e8f1c927
Create Date: 2026-11-11 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e1f5a3d702'
down_revision: Union[str, Sequence[str], None] = 'a6d3e8f1c927'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PADRE = "Inversión"
PROVEEDORES = {"Bit2Me": "bit2me"}


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("inversiones")  # solo tenía aportado_previo, nunca rellenado
    inversiones = op.create_table(
        "inversiones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("proveedor", sa.String(20), nullable=True),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre"),
    )
    op.create_table(
        "aportaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inversion_id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("importe", sa.Numeric(12, 2), nullable=False),
        sa.Column("nota", sa.String(200), nullable=True),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["inversion_id"], ["inversiones.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    conn = op.get_bind()
    filas = conn.execute(sa.text(
        "SELECT h.id, h.name FROM categories h JOIN categories p ON p.id = h.parent_id "
        "WHERE p.name = :padre AND p.parent_id IS NULL AND ("
        " EXISTS (SELECT 1 FROM transactions t WHERE t.category_id = h.id)"
        " OR EXISTS (SELECT 1 FROM manual_asset_entries a WHERE a.name = h.name)) ORDER BY h.name"
    ), {"padre": PADRE}).fetchall()
    op.bulk_insert(inversiones, [
        {"nombre": nombre, "proveedor": PROVEEDORES.get(nombre), "category_id": cid} for cid, nombre in filas
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("aportaciones")
    op.drop_table("inversiones")
    op.create_table(
        "inversiones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("aportado_previo", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id"),
    )
