"""Categorías, subcategorías y reglas de categorización semilla.

La taxonomía de categoría/subcategoría reproduce la que usa la propia ING en
sus extractos (para que resulte familiar al usuario), pero la API de Open
Banking (Enable Banking) no expone esa categorización — solo texto de
descripción — así que las reglas de esta tabla son las que hacen ese trabajo
sobre los movimientos que llegan por la API.
"""

from app.models import AmountSign, BudgetGroup

# (categoría, subcategoría, budget_group, is_transfer_category, recurrente, anual)
# budget_group=None => ambiguo, no se cuenta en el desglose 50/30/20 pero sí en el gasto total.
# recurrente=True => mismo importe (aprox.) todos los meses, un compromiso ya adquirido
# (hipoteca, luz, gimnasio, suscripciones...). recurrente=False => gasto de comportamiento,
# varía según lo que se haga ese mes y es donde tiene sentido intentar recortar (restaurantes,
# cajeros, compras...). Es un eje distinto de budget_group: el gimnasio es DESEO pero
# recurrente; el súper es NECESIDAD pero nada recurrente.
# anual=True (solo tiene sentido con recurrente=True) => dentro de los fijos, cae en bloque
# una o dos veces al año (seguros, IBI) en vez de repartido cada mes.
CATEGORY_TREE: list[tuple[str, str, BudgetGroup | None, bool, bool, bool]] = [
    ("Ahorro", "Redondeo", BudgetGroup.AHORRO, False, True, False),
    ("Alimentación", "Supermercados y alimentación", BudgetGroup.NECESIDAD, False, False, False),
    ("Compras", "Compras (otros)", BudgetGroup.DESEO, False, False, False),
    ("Compras", "Regalos y juguetes", BudgetGroup.DESEO, False, False, False),
    ("Educación y salud", "Deporte y gimnasio", BudgetGroup.DESEO, False, True, False),
    ("Educación y salud", "Farmacia, herbolario y nutrición", BudgetGroup.NECESIDAD, False, False, False),
    ("Hogar", "Alquiler vivienda", BudgetGroup.NECESIDAD, False, True, False),
    ("Hogar", "Hipoteca", BudgetGroup.NECESIDAD, False, True, False),
    ("Hogar", "Luz y gas", BudgetGroup.NECESIDAD, False, True, False),
    ("Hogar", "Mantenimiento del hogar", BudgetGroup.NECESIDAD, False, False, False),
    ("Hogar", "Teléfono, TV e internet", BudgetGroup.NECESIDAD, False, True, False),
    ("Inversión", "Otras inversiones", BudgetGroup.AHORRO, False, True, False),
    ("Movimientos excluidos", "Traspaso entre cuentas", BudgetGroup.EXCLUIDO, True, False, False),
    # Botes, regalos en grupo y recibos del piso alquilado que devuelve la inquilina: lo que
    # pagas por otros y te devuelven no es ni ingreso ni gasto tuyo.
    ("Movimientos excluidos", "Dinero de paso (botes)", BudgetGroup.EXCLUIDO, True, False, False),
    ("Nómina y otras prestaciones", "Nómina o Pensión", BudgetGroup.INGRESO, False, False, False),
    ("Ocio y viajes", "Cafeterías y restaurantes", BudgetGroup.DESEO, False, False, False),
    ("Ocio y viajes", "Cine, teatro y espectáculos", BudgetGroup.DESEO, False, False, False),
    ("Ocio y viajes", "Hotel y alojamiento", BudgetGroup.DESEO, False, False, False),
    ("Ocio y viajes", "Libros, música y videojuegos", BudgetGroup.DESEO, False, False, False),
    ("Otros gastos", "Cajeros", BudgetGroup.DESEO, False, False, False),  # ocio: bares que solo cobran en efectivo
    ("Otros gastos", "Gasto Bizum", BudgetGroup.DESEO, False, False, False),
    ("Otros gastos", "Otros préstamos y avales", BudgetGroup.NECESIDAD, False, True, False),
    ("Otros gastos", "Pago de impuestos", BudgetGroup.NECESIDAD, False, True, True),
    ("Otros gastos", "Seguros", BudgetGroup.NECESIDAD, False, True, True),
    ("Otros gastos", "Suscripciones", BudgetGroup.DESEO, False, True, False),
    ("Otros gastos", "Transferencias", None, False, False, False),
    ("Otros ingresos", "Abono de financiación", BudgetGroup.INGRESO, False, False, False),
    ("Otros ingresos", "Ingreso Bizum", BudgetGroup.INGRESO, False, False, False),
    ("Otros ingresos", "Ingresos de otras entidades", BudgetGroup.INGRESO, False, False, False),
    ("Otros ingresos", "Alquiler cobrado", BudgetGroup.INGRESO, False, False, False),
    ("Vehículo y transporte", "Gasolina y combustible", BudgetGroup.NECESIDAD, False, False, False),
]

# (patrón, es_regex, amount_sign, categoría, subcategoría, prioridad)
# Prioridad más baja = se evalúa antes. Reglas semilla van en el rango 100-999;
# las aprendidas de correcciones del usuario se crean con prioridad < 100.
SEED_RULES: list[tuple[str, bool, AmountSign, str, str, int]] = [
    # Traspasos propios / redondeo — deben ganar a cualquier otra regla de texto.
    ("TRASPASO INTERNO", False, AmountSign.ANY, "Movimientos excluidos", "Traspaso entre cuentas", 100),
    ("TRASPASO EMITIDO", False, AmountSign.ANY, "Movimientos excluidos", "Traspaso entre cuentas", 100),
    ("TRASPASO RECIBIDO", False, AmountSign.ANY, "Movimientos excluidos", "Traspaso entre cuentas", 100),
    ("AHORRO CRECE", False, AmountSign.ANY, "Ahorro", "Redondeo", 100),
    # Nómina / ingresos
    ("NOMINA", False, AmountSign.POSITIVE, "Nómina y otras prestaciones", "Nómina o Pensión", 110),
    ("BIZUM", False, AmountSign.POSITIVE, "Otros ingresos", "Ingreso Bizum", 110),
    ("BIZUM", False, AmountSign.NEGATIVE, "Otros gastos", "Gasto Bizum", 110),
    # Vivienda / suministros
    ("HIPOTECA", False, AmountSign.ANY, "Hogar", "Hipoteca", 120),
    ("ALQUILER", False, AmountSign.ANY, "Hogar", "Alquiler vivienda", 120),
    ("IBERDROLA", False, AmountSign.ANY, "Hogar", "Luz y gas", 130),
    ("ENDESA", False, AmountSign.ANY, "Hogar", "Luz y gas", 130),
    ("NATURGY", False, AmountSign.ANY, "Hogar", "Luz y gas", 130),
    ("ENERGIA", False, AmountSign.ANY, "Hogar", "Luz y gas", 130),
    ("MOVISTAR", False, AmountSign.ANY, "Hogar", "Teléfono, TV e internet", 130),
    ("VODAFONE", False, AmountSign.ANY, "Hogar", "Teléfono, TV e internet", 130),
    ("ORANGE", False, AmountSign.ANY, "Hogar", "Teléfono, TV e internet", 130),
    ("JAZZTEL", False, AmountSign.ANY, "Hogar", "Teléfono, TV e internet", 130),
    # Alimentación
    ("MERCADONA", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    ("CARREFOUR", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    ("LIDL", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    ("DIA ", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    ("ALCAMPO", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    ("CONSUM", False, AmountSign.ANY, "Alimentación", "Supermercados y alimentación", 130),
    # Transporte
    ("REPSOL", False, AmountSign.ANY, "Vehículo y transporte", "Gasolina y combustible", 130),
    ("CEPSA", False, AmountSign.ANY, "Vehículo y transporte", "Gasolina y combustible", 130),
    ("GASOLINERA", False, AmountSign.ANY, "Vehículo y transporte", "Gasolina y combustible", 130),
    # Ocio y suscripciones
    ("NETFLIX", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("SPOTIFY", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("HBO", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("PRIME VIDEO", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("DISNEY", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("RESTAURANTE", False, AmountSign.ANY, "Ocio y viajes", "Cafeterías y restaurantes", 140),
    ("CAFETERIA", False, AmountSign.ANY, "Ocio y viajes", "Cafeterías y restaurantes", 140),
    ("CINE", False, AmountSign.ANY, "Ocio y viajes", "Cine, teatro y espectáculos", 140),
    ("HOTEL", False, AmountSign.ANY, "Ocio y viajes", "Hotel y alojamiento", 140),
    ("BOOKING.COM", False, AmountSign.ANY, "Ocio y viajes", "Hotel y alojamiento", 140),
    ("AIRBNB", False, AmountSign.ANY, "Ocio y viajes", "Hotel y alojamiento", 140),
    # Salud / farmacia
    ("FARMACIA", False, AmountSign.ANY, "Educación y salud", "Farmacia, herbolario y nutrición", 130),
    # Impuestos / cajero
    ("HACIENDA", False, AmountSign.ANY, "Otros gastos", "Pago de impuestos", 130),
    ("AEAT", False, AmountSign.ANY, "Otros gastos", "Pago de impuestos", 130),
    ("CAJERO", False, AmountSign.ANY, "Otros gastos", "Cajeros", 140),
    ("REINTEGRO EFECTIVO", False, AmountSign.ANY, "Otros gastos", "Cajeros", 140),
    # Compras genéricas
    ("AMAZON", False, AmountSign.ANY, "Compras", "Compras (otros)", 200),
    ("EL CORTE INGLES", False, AmountSign.ANY, "Compras", "Compras (otros)", 200),
    ("PCCOMPONENTES", False, AmountSign.ANY, "Compras", "Compras (otros)", 200),
    # Préstamos / impuestos
    ("CARGO CUOTA DE PRESTAMO", False, AmountSign.ANY, "Otros gastos", "Otros préstamos y avales", 130),
    ("SUMA GESTION", False, AmountSign.ANY, "Otros gastos", "Pago de impuestos", 130),
    # Telefonía / gimnasio (marcas vistas en los extractos reales)
    ("LOWNET", False, AmountSign.ANY, "Hogar", "Teléfono, TV e internet", 130),
    ("PALAGYM", False, AmountSign.ANY, "Educación y salud", "Deporte y gimnasio", 130),
    # Inversión
    ("FONDOS-PLANES", False, AmountSign.ANY, "Inversión", "Otras inversiones", 130),
    ("QUANLOOP", False, AmountSign.ANY, "Inversión", "Otras inversiones", 130),
    # Suscripciones de software/streaming adicionales
    ("OPENAI", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("MEETIC", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("SKYSHOWTIME", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
    ("GITHUB", False, AmountSign.ANY, "Otros gastos", "Suscripciones", 130),
]
