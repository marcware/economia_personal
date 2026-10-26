"""Categorización asistida de los movimientos 'sin clasificar' restantes, a partir de
patrones identificados a mano revisando las descripciones reales. Crea reglas permanentes
(is_regex donde hace falta) y recategoriza retroactivamente.

Además de RULES (patrón de texto -> categoría), AMOUNT_RULES resuelve los pocos casos
donde dos conceptos distintos comparten la misma descripción genérica del banco y solo
se distinguen por el importe exacto (p.ej. 'Transferencia emitida periódica' es a la vez
la cuota de comunidad y el traspaso a Bit2Me) — el motor de reglas normal no puede
expresar eso, así que se asigna directamente sobre las transacciones sin categorizar.

Uso:
    python scripts/bulk_categorize_pending.py
"""

from app.categorization.engine import categorize_transaction
from app.categorization.normalize import normalize_description
from app.database import SessionLocal
from app.models import AmountSign, CategorizationRule, Category, Transaction

# (patrón normalizado, es_regex, nombre_categoria, nombre_subcategoria)
RULES: list[tuple[str, bool, str, str]] = [
    # --- Vehículo y transporte: gasolineras, peajes, parking, transporte público ---
    (r"E\.S\.[A-Z ]", True, "Vehículo y transporte", "Gasolina y combustible"),
    ("E S SAN PRUDENCIO", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("TAMOIL", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("PETROBIERZO", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("TANKING", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("SPRINTFUEL", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("FUTURA PETROLIUM", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("PLENERGY", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("US136A", False, "Vehículo y transporte", "Gasolina y combustible"),
    (r"^AUT\. VASCO ARAGONESA", True, "Vehículo y transporte", "Gasolina y combustible"),
    ("AUTOPISTA AP", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("A.S. - AP-6", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("EESS COCENTAINA", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("SEITT", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("PARKING", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("APARCAMIENTO", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("RENFE", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("METRO DE MADRID", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("AEROPUERTO", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("DGT SANCIONES", False, "Vehículo y transporte", "Gasolina y combustible"),
    # --- Alimentación ---
    ("HIPERBER", False, "Alimentación", "Supermercados y alimentación"),
    ("CARNISSERIA", False, "Alimentación", "Supermercados y alimentación"),
    ("COOP AGRICOLA CATOLICA", False, "Alimentación", "Supermercados y alimentación"),
    ("MAS Y MAS", False, "Alimentación", "Supermercados y alimentación"),
    ("ALDI ", False, "Alimentación", "Supermercados y alimentación"),
    ("CARREF ", False, "Alimentación", "Supermercados y alimentación"),
    ("FROIZ", False, "Alimentación", "Supermercados y alimentación"),
    ("SUPERMERCADO", False, "Alimentación", "Supermercados y alimentación"),
    ("SUPER 24", False, "Alimentación", "Supermercados y alimentación"),
    ("GRANIER", False, "Alimentación", "Supermercados y alimentación"),
    ("FORN BORRUIX", False, "Alimentación", "Supermercados y alimentación"),
    ("FORN DE MARIAN", False, "Alimentación", "Supermercados y alimentación"),
    ("PLAZA ABASTOS", False, "Alimentación", "Supermercados y alimentación"),
    ("FONTEXANIA", False, "Alimentación", "Supermercados y alimentación"),
    # --- Ocio y viajes: cafeterías, restaurantes, bares, comida rápida ---
    ("REST ARROCERIA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("SAL Y FIESTA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BAR LLOPIS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BAR POLIDEPORTIVO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BAR LINTON", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BAR DE COMIDAS BOTANA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("IDEAL BAR", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("KFC", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MCDONALD", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MC DONALDS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("GASTROSOMNIS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("STARBUCKS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("PAD THAI", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("OLD ASIA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("KAI XIN SUSHI", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("VORAZ GASTRO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("TABERNA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MOLTA PIZZA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("TATEMA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("SOKAT CUINA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("RTE ", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("VIPS ", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("EL RASPA DE EDU", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("EL RACO DE LA PIZZA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("EL GAT NEGRE", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("GELATERIA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("CANTINA CABEZO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("CAFE PIANOLA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("LA CUCA VIGO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("LA COQUETA SEGOVIA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MYKONOS ALCOY", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MOUAK TORRENTE", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BURDOG MADRID", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("DONDE CECI", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("TRECE PIZZAS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    (r"\bBK\d", True, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("UBER *EATS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("GREEN CAFFE NERO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("SANTAGLORIA", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("IL FORNACCIO", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("SUMUP *", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("PA I DOLCOS", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("BLANC MARKT", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("CASA PLANES", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("MESON EL PARRAL", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("HIPERMAR MASCOTAS", False, "Hogar", "Mascotas"),
    ("TIENDANIMAL", False, "Hogar", "Mascotas"),
    ("KIWOKO", False, "Hogar", "Mascotas"),
    ("TAXDOWN", False, "Otros gastos", "Pago de impuestos"),
    ("VIPS SAN VICENTE", False, "Ocio y viajes", "Cafeterías y restaurantes"),
    ("WIZZ AIR", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("ALBERGUE", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("HOSTEL", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("IBIS BUDGET", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("PENSION D MARIA", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("ATRAPALO.COM", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("TICKETLOC", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("KINEPOLIS", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("IFEMA", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("ENTRADAS EVENTOS", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("DIVERFEST", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    # --- Suscripciones software/streaming ---
    ("HELP.MAX.COM", False, "Otros gastos", "Suscripciones"),
    ("ANTHROPIC", False, "Otros gastos", "Suscripciones"),
    ("CLAUDE.AI SUBSCRIPTION", False, "Otros gastos", "Suscripciones"),
    ("CURSOR, AI POWERED IDE", False, "Otros gastos", "Suscripciones"),
    ("RUNWAY STANDARD PLAN", False, "Otros gastos", "Suscripciones"),
    ("MICROSOFT*XBOX", False, "Otros gastos", "Suscripciones"),
    ("MICROSOFT PAYMENTS", False, "Otros gastos", "Suscripciones"),
    ("UDEMY", False, "Otros gastos", "Suscripciones"),
    ("PROGRAMANDOENJAVA.COM", False, "Otros gastos", "Suscripciones"),
    ("DIGITALOCEAN.COM", False, "Otros gastos", "Suscripciones"),
    ("PIKA.ART", False, "Otros gastos", "Suscripciones"),
    ("ONLYFANS.COM", False, "Otros gastos", "Suscripciones"),
    # --- Compras ---
    # Amazon Prime (cuota anual) es suscripción; gana a la regla semilla genérica "AMAZON",
    # que deja el resto de compras de Amazon en "Compras (otros)".
    ("AMAZON PRIME", False, "Otros gastos", "Suscripciones"),
    ("AMAZON MEDI", False, "Ocio y viajes", "Libros, música y videojuegos"),  # Kindle, cómics
    ("AMZN MKTP", False, "Ocio y viajes", "Libros, música y videojuegos"),  # sobre todo libros y videojuegos
    ("ALIEXPRESS.COM", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("TEMU.COM", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("DECATHLON", False, "Compras", "Ropa y calzado"),
    ("LEROY MERLIN", False, "Hogar", "Mantenimiento del hogar"),
    ("FERRETERIA", False, "Hogar", "Mantenimiento del hogar"),
    ("ELECTRODOMESTICOS", False, "Hogar", "Electrodomésticos"),
    ("FNAC", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("LIBRERIA", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("CASA DEL LIBRO", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("COMIX CITY", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("AKIRA COMICS", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("DETROIT LLIBRES", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("JUGUETTOS", False, "Compras", "Regalos y juguetes"),
    ("MARKETPLACE PCCOM", False, "Compras", "Electrónica e informática"),
    ("CLOTH MEN", False, "Compras", "Ropa y calzado"),
    ("CLOTHMEN", False, "Compras", "Ropa y calzado"),
    ("JYSK", False, "Hogar", "Muebles y decoración"),
    # --- Farmacia / salud ---
    ("FCIA ", False, "Educación y salud", "Farmacia, herbolario y nutrición"),
    # --- Inversión / crypto ---
    ("BIT2ME", False, "Inversión", "Otras inversiones"),
    ("BITCOINFORME", False, "Inversión", "Otras inversiones"),
    (r"PRIMA (MAYO|FEBR|AGOST)\.? +PIAS", True, "Inversión", "Otras inversiones"),
    # --- Préstamos / deudas ---
    ("AMORTIZACION PARCIAL DE PRESTAMO", False, "Otros gastos", "Otros préstamos y avales"),
    ("AMORTIZACION TOTAL DE PRESTAMO", False, "Otros gastos", "Otros préstamos y avales"),
    ("ADEUDO POR EMBARGO", False, "Otros gastos", "Otros préstamos y avales"),
    ("CREDITEX", False, "Otros gastos", "Otros préstamos y avales"),
    ("SUMA. GESTION", False, "Otros gastos", "Pago de impuestos"),
    ("PAGO DE IMPUESTOS", False, "Otros gastos", "Pago de impuestos"),
    # --- Segunda pasada: patrones adicionales identificados ---
    ("KUUPS", False, "Alimentación", "Supermercados y alimentación"),
    ("ESCENA ONLINE", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("SPORT PASSION", False, "Ocio y viajes", "Cafeterías y restaurantes"),  # es un bar, no una tienda
    ("INSTANT GAMING", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("PAYPAL *INSTANTGAMI", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("PNP*ZACATRUS", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("TECNO ESPORT", False, "Vehículo y transporte", "Mantenimiento del vehículo"),
    ("ALMACENES REY DON JAIME", False, "Compras", "Compras (otros)"),
    # --- Tercera pasada (revisión de los 311 pendientes) ---
    ("DEPORVILLAGE", False, "Compras", "Ropa y calzado"),
    ("IBERLIBRO", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("ATENEO COMICS", False, "Ocio y viajes", "Libros, música y videojuegos"),
    ("AELIA DUTY FREE", False, "Compras", "Compras (otros)"),
    ("SP BARCA LICENS", False, "Compras", "Compras (otros)"),
    ("ECOCAMP", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("CONVENTO DE MINIMOS", False, "Ocio y viajes", "Hotel y alojamiento"),
    ("OFICINA DEL PEREGRINO", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    ("CATEDRAL DE", False, "Ocio y viajes", "Cine, teatro y espectáculos"),
    (r"^(PLK|APK)\d", True, "Vehículo y transporte", "Gasolina y combustible"),
    ("AUTOGRILL", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("AREAS ", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("EMPRESA MIXTA DE TRAFICO", False, "Vehículo y transporte", "Gasolina y combustible"),
    ("FISIO ", False, "Educación y salud", "Farmacia, herbolario y nutrición"),
    ("ABONO DE PRESTAMO", False, "Otros ingresos", "Abono de financiación"),
    ("COMISION SIEMPRE CUBIERTO", False, "Otros gastos", "Suscripciones"),
    # Bizum mensual de 50€ a un segundo gimnasio/entrenador (confirmado por Marcos):
    # sin esto caía en el cajón genérico de "Gasto Bizum".
    ("CARLOS SANJUAN LUCAS", False, "Educación y salud", "Deporte y gimnasio"),
]

# (descripción normalizada exacta, importe exacto, categoría, subcategoría). No son
# CategorizationRule (el motor no distingue por importe) — se asignan directamente y
# solo sobre transacciones que sigan sin categorizar, para no pisar nada ya corregido.
AMOUNT_RULES: list[tuple[str, float, str, str]] = [
    # Confirmado contra el Excel: Comunidad es 30€/mes constante, Bit2Me 25€/mes constante,
    # ambos ininterrumpidos en todo el histórico. El -50€ de la misma descripción (7 pagos,
    # ene-jul 2025, ya cerrado) se deja sin decidir — no hay con qué contrastarlo.
    ("TRANSFERENCIA EMITIDA PERIODICA", -30.0, "Otros gastos", "Pago de impuestos"),
    ("TRANSFERENCIA EMITIDA PERIODICA", -25.0, "Inversión", "Otras inversiones"),
]


def get_category_id(db, categorias_cache: dict, categoria: str, subcategoria: str) -> int:
    key = (categoria, subcategoria)
    if key not in categorias_cache:
        cat = None
        for c in db.query(Category).filter_by(name=subcategoria).all():
            if c.parent_id and db.get(Category, c.parent_id).name == categoria:
                cat = c
                break
        if cat is None:
            raise ValueError(f"No existe la categoría {categoria!r} / {subcategoria!r}")
        categorias_cache[key] = cat.id
    return categorias_cache[key]


def main() -> None:
    db = SessionLocal()
    try:
        categorias_cache: dict = {}
        nuevas = 0
        for pattern, is_regex, categoria, subcategoria in RULES:
            category_id = get_category_id(db, categorias_cache, categoria, subcategoria)
            normalized = pattern if is_regex else normalize_description(pattern)
            exists = (
                db.query(CategorizationRule)
                .filter_by(pattern=normalized, category_id=category_id, is_regex=is_regex)
                .one_or_none()
            )
            if exists is None:
                db.add(CategorizationRule(
                    pattern=normalized, is_regex=is_regex, amount_sign=AmountSign.ANY,
                    category_id=category_id, priority=60, created_from_correction=True, active=True,
                ))
                nuevas += 1
        db.commit()
        print(f"{nuevas} reglas nuevas creadas.")

        pendientes = db.query(Transaction).filter(Transaction.category_id.is_(None)).all()
        categorizadas = 0
        for tx in pendientes:
            if categorize_transaction(db, tx):
                categorizadas += 1
        db.commit()
        print(f"Recategorizadas {categorizadas} de {len(pendientes)} transacciones pendientes.")

        asignadas_por_importe = 0
        for descripcion, importe, categoria, subcategoria in AMOUNT_RULES:
            category_id = get_category_id(db, categorias_cache, categoria, subcategoria)
            filas = (
                db.query(Transaction)
                .filter(
                    Transaction.category_id.is_(None),
                    Transaction.description_normalized == descripcion,
                    Transaction.amount == importe,
                )
                .all()
            )
            for tx in filas:
                tx.category_id = category_id
                asignadas_por_importe += 1
        db.commit()
        print(f"{asignadas_por_importe} transacciones asignadas por importe exacto (AMOUNT_RULES).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
