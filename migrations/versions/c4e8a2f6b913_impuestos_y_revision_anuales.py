"""impuestos y revisión del coche como pagos anuales propios

Los recibos de SUMA iban todos a "Pago de impuestos", mezclados con tasas pequeñas y una
transferencia mensual: en /anual y en la hucha de recibos no se veía cada uno. Pasan a
categorías anuales propias, y la revisión anual del coche (Tecno Esport, dic/ene) deja de
ser "Mantenimiento del vehículo", donde contaba como imprevisto.

SUMA cobra todo con la misma descripción, así que las reglas van por importe mínimo
(se evalúa antes la de importe mayor). Se recategoriza el histórico que estaba en "Pago de
impuestos" / "Mantenimiento del vehículo"; lo marcado a mano como dinero de paso no se toca.

Revision ID: c4e8a2f6b913
Revises: b7e3f9a1d462
Create Date: 2026-11-11 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a2f6b913'
down_revision: Union[str, Sequence[str], None] = 'b7e3f9a1d462'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Debe coincidir con CATEGORY_TREE en app/categorization/seed_rules.py.
NUEVAS = [
    ("Otros gastos", "IBI Palacete"),
    ("Otros gastos", "IBI cochera"),
    ("Otros gastos", "Impuesto del coche"),
    ("Vehículo y transporte", "Revisión del coche"),
]
SUMA = r"SUMA\.? GESTION"
# (subcategoría, importe mínimo, prioridad, importe exacto del histórico)
REGLAS_SUMA = [
    ("IBI Palacete", 200, 55, 240.66),
    ("Impuesto del coche", 100, 56, 123.12),
    ("IBI cochera", 60, 57, 74.11),
]

categorias = sa.table(
    "categories",
    sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("parent_id", sa.Integer),
    sa.column("budget_group", sa.String), sa.column("is_system", sa.Boolean),
    sa.column("is_transfer_category", sa.Boolean), sa.column("recurrente", sa.Boolean), sa.column("anual", sa.Boolean),
)
reglas = sa.table(
    "categorization_rules",
    sa.column("id", sa.Integer), sa.column("pattern", sa.String), sa.column("is_regex", sa.Boolean),
    sa.column("amount_sign", sa.String), sa.column("min_abs_amount", sa.Numeric), sa.column("category_id", sa.Integer),
    sa.column("priority", sa.Integer), sa.column("created_from_correction", sa.Boolean), sa.column("active", sa.Boolean),
    sa.column("match_count", sa.Integer),
)
movimientos = sa.table(
    "transactions",
    sa.column("id", sa.Integer), sa.column("amount", sa.Numeric), sa.column("category_id", sa.Integer),
    sa.column("description_normalized", sa.String),
)


def _id(conn, padre: str, nombre: str) -> int | None:
    p = categorias.alias("p")
    fila = conn.execute(
        sa.select(categorias.c.id).join(p, p.c.id == categorias.c.parent_id)
        .where(p.c.name == padre, categorias.c.name == nombre)
    ).first()
    return fila.id if fila else None


def upgrade() -> None:
    conn = op.get_bind()
    padres = {r.name: r.id for r in conn.execute(
        sa.select(categorias.c.id, categorias.c.name).where(categorias.c.parent_id.is_(None)))}
    ids = {}
    for padre, nombre in NUEVAS:
        if padre not in padres:
            continue
        ids[nombre] = _id(conn, padre, nombre)
        if ids[nombre] is None:
            conn.execute(categorias.insert().values(
                name=nombre, parent_id=padres[padre], budget_group="NECESIDAD", is_system=True,
                is_transfer_category=False, recurrente=True, anual=True,
            ))
            ids[nombre] = _id(conn, padre, nombre)

    impuestos = _id(conn, "Otros gastos", "Pago de impuestos")
    for nombre, minimo, prioridad, exacto in REGLAS_SUMA:
        if ids.get(nombre) is None:
            continue
        conn.execute(reglas.insert().values(
            pattern=SUMA, is_regex=True, amount_sign="NEGATIVE", min_abs_amount=minimo, category_id=ids[nombre],
            priority=prioridad, created_from_correction=False, active=True, match_count=0,
        ))
        if impuestos is not None:
            for fila in conn.execute(sa.select(movimientos.c.id, movimientos.c.description_normalized).where(
                    movimientos.c.category_id == impuestos, movimientos.c.amount == -exacto)):
                if "SUMA" in fila.description_normalized:
                    conn.execute(movimientos.update().where(movimientos.c.id == fila.id).values(category_id=ids[nombre]))

    revision_id, mantenimiento = ids.get("Revisión del coche"), _id(conn, "Vehículo y transporte", "Mantenimiento del vehículo")
    if revision_id is not None and mantenimiento is not None:
        conn.execute(reglas.update().where(reglas.c.pattern == "TECNO ESPORT").values(category_id=revision_id))
        conn.execute(movimientos.update().where(
            movimientos.c.category_id == mantenimiento,
            movimientos.c.description_normalized.like("%TECNO ESPORT%"),
        ).values(category_id=revision_id))


def downgrade() -> None:
    conn = op.get_bind()
    impuestos = _id(conn, "Otros gastos", "Pago de impuestos")
    mantenimiento = _id(conn, "Vehículo y transporte", "Mantenimiento del vehículo")
    for padre, nombre in NUEVAS:
        cid = _id(conn, padre, nombre)
        if cid is None:
            continue
        destino = mantenimiento if nombre == "Revisión del coche" else impuestos
        conn.execute(movimientos.update().where(movimientos.c.category_id == cid).values(category_id=destino))
        conn.execute(reglas.update().where(reglas.c.category_id == cid, reglas.c.pattern == "TECNO ESPORT")
                     .values(category_id=mantenimiento))
        conn.execute(reglas.delete().where(reglas.c.category_id == cid))
        conn.execute(categorias.delete().where(categorias.c.id == cid))
