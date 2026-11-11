"""inversiones

Apartado /inversiones. Cada inversión es una subcategoría de "Inversión" (AHORRO): se
parte "Otras inversiones" en Bit2Me, Trade Republic, Quanloop, Plan de pensiones ING y
PIAS Mediolanum, moviendo sus reglas y recategorizando el histórico por descripción, para
saber cuánto se ha aportado a cada una. Tabla nueva `inversiones` (aportado antes del
histórico).
El valor declarado del plan de ING pasa a llamarse como su subcategoría.

Revision ID: f4a7c2e9b815
Revises: e8c3a5f1d204
Create Date: 2026-11-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a7c2e9b815'
down_revision: Union[str, Sequence[str], None] = 'e8c3a5f1d204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PADRE = "Inversión"
ORIGEN = "Otras inversiones"
# subcategoría -> fragmentos (LIKE, sobre la descripción normalizada y sobre el patrón de
# la regla) que la identifican. Deben coincidir con CATEGORY_TREE / SEED_RULES.
NUEVAS = {
    "Bit2Me": ["BIT2ME", "BITCOINFORME", "TRANSFERENCIA EMITIDA PERIODICA"],
    "Trade Republic": ["TRADE REPUBLIC", "TRBKESM2"],
    "Quanloop": ["QUANLOOP"],
    "Plan de pensiones ING": ["FONDOS-PLANES"],
    "PIAS Mediolanum": ["PIAS"],
}
ACTIVO_PLAN = ("ING Plan 2050%", "Plan de pensiones ING")

categorias = sa.table(
    "categories",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("parent_id", sa.Integer),
    sa.column("budget_group", sa.String),
    sa.column("is_system", sa.Boolean),
    sa.column("is_transfer_category", sa.Boolean),
    sa.column("recurrente", sa.Boolean),
    sa.column("anual", sa.Boolean),
)
movimientos = sa.table(
    "transactions",
    sa.column("id", sa.Integer),
    sa.column("category_id", sa.Integer),
    sa.column("description_normalized", sa.String),
)
reglas = sa.table(
    "categorization_rules",
    sa.column("id", sa.Integer),
    sa.column("pattern", sa.String),
    sa.column("category_id", sa.Integer),
)
activos = sa.table("manual_asset_entries", sa.column("name", sa.String))


def _padre(conn) -> int | None:
    return conn.execute(
        sa.select(categorias.c.id).where(categorias.c.parent_id.is_(None), categorias.c.name == PADRE)
    ).scalar()


def _hija(conn, padre_id: int, nombre: str) -> int | None:
    return conn.execute(
        sa.select(categorias.c.id).where(categorias.c.parent_id == padre_id, categorias.c.name == nombre)
    ).scalar()


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "inversiones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("aportado_previo", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id"),
    )
    conn = op.get_bind()
    padre_id = _padre(conn)
    if padre_id is None:  # base sin sembrar: seed_categories crea el árbol completo
        return
    origen_id = _hija(conn, padre_id, ORIGEN)
    for nombre, fragmentos in NUEVAS.items():
        cid = _hija(conn, padre_id, nombre)
        if cid is None:
            conn.execute(categorias.insert().values(
                name=nombre, parent_id=padre_id, budget_group="AHORRO", is_system=True,
                is_transfer_category=False, recurrente=True, anual=False,
            ))
            cid = _hija(conn, padre_id, nombre)
        if origen_id is None:
            continue
        for f in fragmentos:
            conn.execute(movimientos.update().where(
                movimientos.c.category_id == origen_id,
                movimientos.c.description_normalized.like(f"%{f}%"),
            ).values(category_id=cid))
            conn.execute(reglas.update().where(
                reglas.c.category_id == origen_id, reglas.c.pattern.like(f"%{f}%"),
            ).values(category_id=cid))

    conn.execute(activos.update().where(activos.c.name.like(ACTIVO_PLAN[0])).values(name=ACTIVO_PLAN[1]))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    padre_id = _padre(conn)
    origen_id = _hija(conn, padre_id, ORIGEN) if padre_id is not None else None
    if origen_id is not None:
        for nombre in NUEVAS:
            cid = _hija(conn, padre_id, nombre)
            if cid is None:
                continue
            conn.execute(movimientos.update().where(movimientos.c.category_id == cid).values(category_id=origen_id))
            conn.execute(reglas.update().where(reglas.c.category_id == cid).values(category_id=origen_id))
            conn.execute(categorias.delete().where(categorias.c.id == cid))
    conn.execute(activos.update().where(activos.c.name == ACTIVO_PLAN[1]).values(name="ING Plan 2050 (jubilación, 125€/mes)"))
    op.drop_table("inversiones")
