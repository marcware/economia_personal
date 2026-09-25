"""desglose de compras (otros)

"Compras · Compras (otros)" era un cajón de sastre: el gato, libros, ropa, informática,
un bar y el taller del coche caían juntos. Marcos ha dicho a qué va cada comercio:

- Subcategorías nuevas (si no existen ya): Hogar · Mascotas, Hogar · Muebles y
  decoración, Compras · Ropa y calzado, Compras · Electrónica e informática y
  Vehículo y transporte · Mantenimiento del vehículo.
- Las reglas de esos comercios apuntan ahora a su subcategoría, y los movimientos ya
  categorizados en "Compras (otros)" por esas reglas se mueven con ellas (salvo los
  corregidos a mano). Amazon genérico y El Corte Inglés se quedan en "Compras (otros)".

Revision ID: a9e3c1f7d240
Revises: e2b7c4d9a613
Create Date: 2026-09-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e3c1f7d240'
down_revision: Union[str, Sequence[str], None] = 'e2b7c4d9a613'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (padre, subcategoría, budget_group). Debe coincidir con CATEGORY_TREE en
# app/categorization/seed_rules.py.
NUEVAS = [
    ("Hogar", "Mascotas", "NECESIDAD"),
    ("Hogar", "Muebles y decoración", "DESEO"),
    ("Compras", "Ropa y calzado", "DESEO"),
    ("Compras", "Electrónica e informática", "DESEO"),
    ("Vehículo y transporte", "Mantenimiento del vehículo", "NECESIDAD"),
]

ORIGEN = ("Compras", "Compras (otros)")

# patrón de regla (ya normalizado) -> (padre, subcategoría) de destino.
REASIGNAR = {
    "HIPERMAR MASCOTAS": ("Hogar", "Mascotas"),
    "TIENDANIMAL": ("Hogar", "Mascotas"),
    "KIWOKO": ("Hogar", "Mascotas"),
    # En Amazon Marketplace, AliExpress y Temu compra sobre todo libros y videojuegos.
    "AMZN MKTP": ("Ocio y viajes", "Libros, música y videojuegos"),
    "ALIEXPRESS.COM": ("Ocio y viajes", "Libros, música y videojuegos"),
    "TEMU.COM": ("Ocio y viajes", "Libros, música y videojuegos"),
    "FNAC": ("Ocio y viajes", "Libros, música y videojuegos"),
    "LIBRERIA": ("Ocio y viajes", "Libros, música y videojuegos"),
    "CASA DEL LIBRO": ("Ocio y viajes", "Libros, música y videojuegos"),
    "COMIX CITY": ("Ocio y viajes", "Libros, música y videojuegos"),
    "AKIRA COMICS": ("Ocio y viajes", "Libros, música y videojuegos"),
    "DETROIT LLIBRES": ("Ocio y viajes", "Libros, música y videojuegos"),
    "IBERLIBRO": ("Ocio y viajes", "Libros, música y videojuegos"),
    "ATENEO COMICS": ("Ocio y viajes", "Libros, música y videojuegos"),
    "DECATHLON": ("Compras", "Ropa y calzado"),
    "DEPORVILLAGE": ("Compras", "Ropa y calzado"),
    "CLOTH MEN": ("Compras", "Ropa y calzado"),
    "CLOTHMEN": ("Compras", "Ropa y calzado"),
    "PCCOMPONENTES": ("Compras", "Electrónica e informática"),
    "MARKETPLACE PCCOM": ("Compras", "Electrónica e informática"),
    "JYSK": ("Hogar", "Muebles y decoración"),
    "SPORT PASSION": ("Ocio y viajes", "Cafeterías y restaurantes"),  # es un bar
    "TECNO ESPORT": ("Vehículo y transporte", "Mantenimiento del vehículo"),  # taller
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
    sa.column("is_regex", sa.Boolean),
    sa.column("category_id", sa.Integer),
)
presupuestos = sa.table("budgets", sa.column("category_id", sa.Integer))
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


def _mover(conn, hojas, desde_de, hacia_de) -> None:
    """Para cada patrón, repunta sus reglas y sus movimientos no corregidos a mano."""
    for patron, destino in REASIGNAR.items():
        desde, hacia = hojas.get(desde_de(destino)), hojas.get(hacia_de(destino))
        if desde is None or hacia is None:
            continue
        conn.execute(
            reglas.update()
            .where(reglas.c.pattern == patron, reglas.c.is_regex.is_(False), reglas.c.category_id == desde)
            .values(category_id=hacia)
        )
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
    hojas = _hojas(conn)
    padres = {
        row.name: row.id
        for row in conn.execute(sa.select(categorias.c.id, categorias.c.name).where(categorias.c.parent_id.is_(None)))
    }
    for padre, nombre, grupo in NUEVAS:
        if padre in padres and (padre, nombre) not in hojas:
            conn.execute(categorias.insert().values(
                name=nombre, parent_id=padres[padre], budget_group=grupo, is_system=True,
                is_transfer_category=False, recurrente=False, anual=False,
            ))
    # "AMZN MKTP" en bulk_categorize_pending.py se guardó como regex; es un literal sin
    # metacaracteres, así que se trata igual que el resto.
    conn.execute(reglas.update().where(reglas.c.pattern == "AMZN MKTP").values(is_regex=False))

    _mover(conn, _hojas(conn), lambda _: ORIGEN, lambda destino: destino)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    hojas = _hojas(conn)
    _mover(conn, hojas, lambda destino: destino, lambda _: ORIGEN)
    # Solo se borran las subcategorías nuevas que hayan quedado vacías.
    for padre, nombre, _ in NUEVAS:
        cid = hojas.get((padre, nombre))
        if cid is None:
            continue
        usada = conn.execute(sa.select(movimientos.c.id).where(movimientos.c.category_id == cid).limit(1)).first()
        con_reglas = conn.execute(sa.select(reglas.c.id).where(reglas.c.category_id == cid).limit(1)).first()
        if usada is None and con_reglas is None:
            conn.execute(presupuestos.delete().where(presupuestos.c.category_id == cid))
            conn.execute(categorias.delete().where(categorias.c.id == cid))
