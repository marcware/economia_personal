"""electrodomesticos y kindle

- Subcategoría nueva Hogar · Electrodomésticos (NECESIDAD): reponer un electrodoméstico
  roto no es un capricho, a diferencia de los muebles y la decoración.
- La regla "ELECTRODOMESTICOS" y sus movimientos salen de Compras (otros) hacia ella.
- Los cargos "AMAZON MEDI*" (Amazon Media: libros de Kindle, cómics) pasan a Libros,
  música y videojuegos; su regla la crea scripts/bulk_categorize_pending.py.

Revision ID: c7a2e9d4b153
Revises: b4f8d2e6a917
Create Date: 2026-09-25 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a2e9d4b153'
down_revision: Union[str, Sequence[str], None] = 'b4f8d2e6a917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ORIGEN = ("Compras", "Compras (otros)")
NUEVA = ("Hogar", "Electrodomésticos", "NECESIDAD")  # debe coincidir con CATEGORY_TREE
# patrón (normalizado) -> destino
MOVER = {
    "ELECTRODOMESTICOS": ("Hogar", "Electrodomésticos"),
    "AMAZON MEDI": ("Ocio y viajes", "Libros, música y videojuegos"),
}

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
reglas = sa.table(
    "categorization_rules",
    sa.column("id", sa.Integer),
    sa.column("pattern", sa.String),
    sa.column("category_id", sa.Integer),
)
movimientos = sa.table(
    "transactions",
    sa.column("id", sa.Integer),
    sa.column("description_normalized", sa.Text),
    sa.column("category_id", sa.Integer),
    sa.column("manually_categorized", sa.Boolean),
)


def _hojas(conn) -> dict[tuple[str, str], int]:
    padre = categorias.alias("padre")
    filas = conn.execute(
        sa.select(categorias.c.id, padre.c.name, categorias.c.name)
        .select_from(categorias.join(padre, categorias.c.parent_id == padre.c.id))
    )
    return {(p, h): cid for cid, p, h in filas}


def _mover(conn, hojas, hacia_origen: bool) -> None:
    for patron, destino in MOVER.items():
        desde, hacia = hojas.get(ORIGEN), hojas.get(destino)
        if desde is None or hacia is None:
            continue
        if hacia_origen:
            desde, hacia = hacia, desde
        conn.execute(reglas.update().where(reglas.c.pattern == patron, reglas.c.category_id == desde)
                     .values(category_id=hacia))
        conn.execute(
            movimientos.update()
            .where(
                movimientos.c.category_id == desde,
                movimientos.c.manually_categorized.is_(False),
                movimientos.c.description_normalized.contains(patron, autoescape=True),
            )
            .values(category_id=hacia)
        )


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    padre, nombre, grupo = NUEVA
    if (padre, nombre) not in _hojas(conn):
        parent_id = conn.execute(
            sa.select(categorias.c.id).where(categorias.c.parent_id.is_(None), categorias.c.name == padre)
        ).scalar()
        if parent_id is not None:
            conn.execute(categorias.insert().values(
                name=nombre, parent_id=parent_id, budget_group=grupo, is_system=True,
                is_transfer_category=False, recurrente=False, anual=False,
            ))
    _mover(conn, _hojas(conn), hacia_origen=False)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    hojas = _hojas(conn)
    _mover(conn, hojas, hacia_origen=True)
    cid = hojas.get(NUEVA[:2])
    if cid is None:
        return
    usada = conn.execute(sa.select(movimientos.c.id).where(movimientos.c.category_id == cid).limit(1)).first()
    con_reglas = conn.execute(sa.select(reglas.c.id).where(reglas.c.category_id == cid).limit(1)).first()
    if usada is None and con_reglas is None:
        presupuestos = sa.table("budgets", sa.column("category_id", sa.Integer))
        conn.execute(presupuestos.delete().where(presupuestos.c.category_id == cid))
        conn.execute(categorias.delete().where(categorias.c.id == cid))
