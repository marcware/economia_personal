"""Avisos de hábitos: gastos hormiga del mes y la base de la pirámide (colchón y deuda).

La aritmética vive en hormiga_service y libertad_service; aquí solo se redacta.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.advisor.types import Advice
from app.services import budget_service, hormiga_service, libertad_service
from app.formato import eur

# El mes se marca como "más hormiga de lo normal" por encima de este múltiplo de la media...
MULTIPLO_HORMIGA = 1.25
# ...y de esta diferencia absoluta, para no avisar por 5 €.
DIFERENCIA_MIN_HORMIGA = 15.0
# Por debajo de este coste anual no merece un consejo.
ANUAL_MIN_HORMIGA = 300.0
MESES_COLCHON_MINIMO = 3


def check_hormiga(db: Session, year: int, month: int) -> list[Advice]:
    h = hormiga_service.resumen(db, year, month)
    if h["num"] == 0:
        return []
    donde = f" Donde más: {h['comercios'][0]['nombre']}." if h["comercios"] else ""
    if h["total"] > h["media_mensual"] * MULTIPLO_HORMIGA and h["total"] - h["media_mensual"] > DIFERENCIA_MIN_HORMIGA:
        return [Advice(
            "gastos_hormiga", "warning", "Más gastos hormiga de lo habitual",
            f"Llevas {h['num']} compras pequeñas por {eur(h['total'])} este mes, frente a una media de "
            f"{eur(h['media_mensual'])}.{donde}",
            f"/dashboard?year={year}&month={month}",
        )]
    if h["anual"] >= ANUAL_MIN_HORMIGA:
        return [Advice(
            "gastos_hormiga", "info", "Gastos hormiga",
            f"A tu ritmo, las compras de hasta {eur(h['importe_max'], 0)} suman {eur(h['anual'], 0)} al año; "
            f"invertidos {h['años']} años serían ~{eur(h['invertido'], 0)}.{donde}",
            f"/dashboard?year={year}&month={month}",
        )]
    return []


def check_base(db: Session, year: int, month: int) -> list[Advice]:
    """Colchón y deuda de consumo. Es una foto de hoy, así que solo se da en el mes en curso."""
    hoy = date.today()
    if (year, month) != (hoy.year, hoy.month):
        return []
    l = libertad_service.resumen(db)
    advices = []
    real, plan = l["real"], l["plan"]
    deficit_real = real["consumo"] - real["ingresos"]
    if plan is not None and plan["consumo"] > plan["ingresos"]:
        advices.append(Advice(
            "deficit", "danger", "Tu presupuesto gasta más de lo que ingresas",
            f"El plan de {plan['nombre']} consume {eur(plan['consumo'], 0)} al mes (con las huchas) y "
            f"entran {eur(plan['ingresos'], 0)}: {eur(plan['consumo'] - plan['ingresos'], 0)} al mes que "
            "saldrían del colchón. Es lo primero que hay que cerrar.",
            f"/presupuestos?year={plan['year']}&month={plan['month']}",
        ))
    elif plan is not None and real["ingresos"] > 0 and deficit_real > 0:
        advices.append(Advice(
            "deficit", "info", "El plan cuadra; los últimos meses no",
            f"En los últimos {l['meses_media']} meses cerrados gastaste de media {eur(real['consumo'], 0)} "
            f"al mes e ingresaste {eur(real['ingresos'], 0)}. El presupuesto de {plan['nombre']} ya cabe "
            f"(deja {eur(plan['ingresos'] - plan['consumo'], 0)} al mes para invertir y ahorrar): ahora toca cumplirlo.",
            f"/presupuestos?year={plan['year']}&month={plan['month']}",
        ))
    elif plan is None and real["ingresos"] > 0 and deficit_real > 0:
        advices.append(Advice(
            "deficit", "danger", "Gastas más de lo que ingresas",
            f"En los últimos {l['meses_media']} meses cerrados has gastado de media "
            f"{eur(real['consumo'], 0)} al mes e ingresado {eur(real['ingresos'], 0)}: "
            f"{eur(deficit_real, 0)} al mes que salen del colchón o de préstamos. Es lo primero que "
            "hay que cerrar, antes que cualquier presupuesto concreto.",
            "/patrimonio",
        ))
    if l["meses_colchon"] is not None and l["meses_colchon"] < MESES_COLCHON_MINIMO:
        advices.append(Advice(
            "colchon", "warning", "Colchón de emergencia corto",
            f"Tu colchón cubre {l['meses_colchon']:.1f} meses de gastos esenciales; lo mínimo son "
            f"{MESES_COLCHON_MINIMO} y lo recomendable {l['meses_colchon_objetivo']} "
            f"({eur(l['objetivo_colchon'], 0)}). Sin él, cualquier imprevisto acaba en préstamo.",
            "/patrimonio",
        ))
        inversion = budget_service.inversion_esperada(db, year, month)
        if inversion > 0:
            advices.append(Advice(
                "inversion_vs_colchon", "info", "Inversión y colchón tiran en direcciones opuestas",
                f"Tienes el compromiso de invertir {eur(inversion, 0)} este mes con un colchón de "
                f"{l['meses_colchon']:.1f} meses. Lo habitual es llenar primero el colchón; si "
                "prefieres seguir invirtiendo, que sea una decisión y no una inercia.",
                f"/presupuestos?year={year}&month={month}",
            ))
    if l["total_deuda_consumo"] > 0:
        advices.append(Advice(
            "deuda_consumo", "info", "Deuda de consumo pendiente",
            f"Debes {eur(l['total_deuda_consumo'], 0)} en préstamos personales. Antes de subir la "
            "inversión, amortizar anticipadamente el de mayor TAE es una rentabilidad segura; "
            "y evita financiar compras nuevas.",
            "/patrimonio",
        ))
    return advices
