"""Carga en presupuestos mensuales la hoja anual que Marcos mantenía a mano.

Los importes se extrajeron de data/2026_Gastos.xlsx (pestaña «Marcos») y están
congelados aquí a propósito: la hoja de cálculo deja de ser la fuente de verdad en
cuanto se ejecuta esto, y un script que dependiera de un Excel editado a mano (con
filas de totales, una pestaña duplicada obsoleta y una fórmula rota en abril) sería
una fuente de errores permanente.

Los ingresos de la hoja (Alquiler +400/mes, Nómina +2810/mes) y el traspaso interno a
ING (-2400/mes) NO se presupuestan: un abs() ingenuo habría creado un "presupuesto"
de 400 € para un cobro.

Uso:
    python scripts/seed_presupuestos.py 2026 11              # solo noviembre
    python scripts/seed_presupuestos.py 2026                 # los 12 meses
    python scripts/seed_presupuestos.py 2026 11 --con-variables
    python scripts/seed_presupuestos.py 2026 11 --dry-run
    python scripts/seed_presupuestos.py 2026 11 --sobrescribir
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Category  # noqa: E402
from app.services import budget_service  # noqa: E402
from app.services.dashboard_service import MONTHS_ES  # noqa: E402

# (categoría padre, subcategoría hoja) -> 12 límites (enero..diciembre) en euros positivos.
# Gastos fijos, procedentes del Excel anual.
PLANTILLA_FIJOS: list[tuple[str, str, list[float]]] = [
    ("Otros gastos", "Otros préstamos y avales",
     [463.77, 463.77, 463.77, 463.77, 463.77, 411.77, 411.77, 411.77, 411.77, 411.77, 411.77, 411.77]),
    ("Hogar", "Hipoteca",
     [276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38, 276.38]),
    # "Inversión · Otras inversiones" NO se presupuesta: un presupuesto es un tope
    # máximo ("Límite mensual"), y capar la inversión manda el mensaje contrario a lo
    # que se busca. Ese objetivo se fija como hito INVERSION_MIN (ver seed de hitos
    # más abajo o la sección "Hitos" de /presupuestos), que sí modela un mínimo.
    # Octubre iba a 0 en la hoja por un abono de +67,84 € mal metido como gasto negativo;
    # se sustituye por el importe de referencia de los meses de invierno.
    ("Hogar", "Luz y gas",
     [114.43, 114.10, 79.53, 115.96, 47.22, 47.22, 77.22, 47.22, 47.22, 128.00, 128.00, 128.00]),
    ("Educación y salud", "Deporte y gimnasio",
     [95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00, 95.00]),
    ("Otros gastos", "Pago de impuestos",
     [136.60, 30.00, 30.00, 167.30, 247.90, 114.13, 136.60, 30.00, 30.00, 376.60, 86.09, 30.00]),
    ("Hogar", "Teléfono, TV e internet",
     [60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71, 60.71]),
    ("Otros gastos", "Suscripciones",
     [76.45, 78.86, 44.46, 62.46, 34.47, 36.47, 36.47, 36.47, 36.47, 36.47, 36.47, 36.47]),
    ("Otros gastos", "Seguros",
     [622.24, 0.00, 222.35, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]),
]

# Gasto variable: la hoja anual no lo cubre (solo llega al ~52% del gasto real), así que
# estos topes salen del histórico real de 2026 con un objetivo de reducción encima.
# Son iguales todos los meses.
VARIABLES_SUGERIDAS: list[tuple[str, str, float]] = [
    ("Otros gastos", "Cajeros", 250.00),                       # media real 533/mes
    ("Compras", "Compras (otros)", 150.00),
    ("Alimentación", "Supermercados y alimentación", 120.00),  # parte se esconde hoy en Cajeros
    ("Otros gastos", "Gasto Bizum", 80.00),                    # media real 104/mes
    ("Ocio y viajes", "Cafeterías y restaurantes", 70.00),
    ("Ocio y viajes", "Hotel y alojamiento", 50.00),
    ("Vehículo y transporte", "Gasolina y combustible", 40.00),
    ("Ocio y viajes", "Cine, teatro y espectáculos", 35.00),
    ("Ocio y viajes", "Libros, música y videojuegos", 25.00),
    ("Educación y salud", "Farmacia, herbolario y nutrición", 15.00),
]

# Conceptos de la hoja que aún no tienen subcategoría donde caer. Ninguno tiene importe
# en noviembre, así que no bloquean el objetivo inmediato.
SIN_HOJA_DESTINO = {
    "Dolçaina (240 €/año)": "haría falta 'Educación y salud · Formación y cursos'",
    "UNESCO (40 €/año)": "haría falta 'Educación y salud · Formación y cursos'",
    "Revisión coche (400 € en diciembre)": "haría falta 'Vehículo y transporte · Mantenimiento'",
}


def _resolver_hojas(db) -> dict[tuple[str, str], int]:
    """Mapa (padre, hoja) -> category_id. Falla ruidosamente si falta alguna."""
    indice = {}
    for cat in db.query(Category).filter(Category.parent_id.isnot(None)).all():
        indice[(cat.parent.name, cat.name)] = cat.id

    necesarias = {(p, h) for p, h, _ in PLANTILLA_FIJOS} | {(p, h) for p, h, _ in VARIABLES_SUGERIDAS}
    faltan = sorted(necesarias - set(indice))
    if faltan:
        raise SystemExit(
            "No existen estas subcategorías en la base de datos:\n"
            + "\n".join(f"  - {p} · {h}" for p, h in faltan)
            + "\nEjecuta primero scripts/seed_categories.py."
        )
    return indice


def plantilla_mes(indice: dict[tuple[str, str], int], month: int, con_variables: bool) -> dict[int, float]:
    """{category_id: límite} para un mes. Omite los importes a cero."""
    plantilla: dict[int, float] = {}
    for padre, hoja, meses in PLANTILLA_FIJOS:
        importe = meses[month - 1]
        if importe > 0:
            plantilla[indice[(padre, hoja)]] = importe
    if con_variables:
        for padre, hoja, importe in VARIABLES_SUGERIDAS:
            plantilla[indice[(padre, hoja)]] = importe
    return plantilla


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        raise SystemExit(__doc__)

    year = int(args[0])
    meses = [int(args[1])] if len(args) > 1 else list(range(1, 13))
    dry_run = "--dry-run" in flags
    sobrescribir = "--sobrescribir" in flags
    con_variables = "--con-variables" in flags

    db = SessionLocal()
    try:
        indice = _resolver_hojas(db)
        etiquetas = {cid: f"{p} · {h}" for (p, h), cid in indice.items()}

        total_escritos = 0
        for month in meses:
            plantilla = plantilla_mes(indice, month, con_variables)
            total = sum(plantilla.values())
            print(f"\n=== {MONTHS_ES[month]} {year} — {len(plantilla)} presupuestos, {total:,.2f} € ===")
            for cid, importe in sorted(plantilla.items(), key=lambda kv: -kv[1]):
                print(f"  {etiquetas[cid]:48} {importe:9,.2f} €")

            if dry_run:
                continue
            escritos = budget_service.seed_month(db, year, month, plantilla, sobrescribir=sobrescribir)
            total_escritos += escritos
            omitidos = len(plantilla) - escritos
            print(f"  -> {escritos} escritos" + (f", {omitidos} ya existían (no tocados)" if omitidos else ""))

        if dry_run:
            print("\n(--dry-run: no se ha escrito nada)")
        else:
            print(f"\nTotal escrito: {total_escritos} presupuestos.")

        if not con_variables:
            print("\nNota: esto son solo los gastos FIJOS de la hoja anual. El gasto variable")
            print("(cajeros, súper, ocio...) es más de la mitad del gasto real: añádelo con --con-variables.")
        print("\nConceptos de la hoja que aún no se pueden presupuestar:")
        for concepto, motivo in SIN_HOJA_DESTINO.items():
            print(f"  - {concepto}: {motivo}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
