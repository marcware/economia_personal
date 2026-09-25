"""Informe de revisión mensual — pensado para que el asistente lo ejecute como primer
paso cuando el usuario pida "revisa mis cuentas", en vez de reconstruir todo a mano
con consultas ad-hoc cada vez.

Uso:
    python scripts/informe_mensual.py [year] [month]   # por defecto, mes en curso
"""

import sys
from datetime import date

from sqlalchemy import func

from app.advisor.engine import get_advice
from app.database import SessionLocal
from app.models import FinancialNote, Transaction, TransferCandidate, TransferCandidateStatus
from app.services import disponible_service, hormiga_service, libertad_service
from app.services.budget_service import budget_summary
from app.services.dashboard_service import MONTHS_ES, monthly_summary
from app.services.goal_service import goal_rows
from app.services.transfer_detector import find_candidates


def _mes_anterior(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def main(year: int, month: int) -> None:
    db = SessionLocal()
    try:
        print(f"=== Informe mensual — {MONTHS_ES[month]} {year} ===\n")

        nuevos = find_candidates(db)
        pendientes_traspaso = (
            db.query(TransferCandidate).filter_by(status=TransferCandidateStatus.PENDING).count()
        )
        if pendientes_traspaso:
            print(
                f"⚠ AUTOTRASPASOS: {pendientes_traspaso} candidato(s) pendientes de confirmar "
                f"({nuevos} nuevos en esta pasada) — revisa /autotraspasos antes de fiarte de las cifras.\n"
            )

        summary = monthly_summary(db, year, month)
        print(f"Ingresos: {summary['ingresos']:.2f}€ | Gastos: {summary['gastos']:.2f}€ "
              f"| Ahorro: {summary['ahorro']:.2f}€", end="")
        if summary["tasa_ahorro"] is not None:
            print(f" ({summary['tasa_ahorro']}%)")
        else:
            print()

        comparativas = []
        y, m = year, month
        for _ in range(3):
            y, m = _mes_anterior(y, m)
            comparativas.append(monthly_summary(db, y, m))
        ingresos_prev = [c["ingresos"] for c in comparativas if c["ingresos"]]
        gastos_prev = [c["gastos"] for c in comparativas if c["gastos"]]
        if ingresos_prev and gastos_prev:
            print(f"Media 3 meses previos: ingresos {sum(ingresos_prev)/len(ingresos_prev):.2f}€, "
                  f"gastos {sum(gastos_prev)/len(gastos_prev):.2f}€")

        print("\nTop categorías de gasto del mes:")
        for c in summary["desglose_categorias"][:8]:
            print(f"  {c['importe']:>9.2f}€  {c['categoria']}")

        resumen_presupuestos = budget_summary(db, year, month)
        if resumen_presupuestos["filas"]:
            print("\nPresupuestos del mes:")
            marcas = {"over": "!!", "near": " ~", "ok": "  ", "cumplido": " OK", "riesgo": " ~", "incumplido": "!!", "pendiente": " .."}
            for f in resumen_presupuestos["filas"]:
                marca = marcas.get(f["estado"], "  ")
                print(
                    f"  {marca} {f['etiqueta']:45} {f['gasto']:>8.2f}€ / {f['limite']:>8.2f}€"
                    f"  ({f['ratio']:.0f}%)"
                )
            print(
                f"     {'TOTAL':45} {resumen_presupuestos['total_gasto']:>8.2f}€ / "
                f"{resumen_presupuestos['total_limite']:>8.2f}€"
            )
        if resumen_presupuestos["sin_presupuesto"]:
            print("\n  Con gasto pero sin presupuesto:")
            for s_ in resumen_presupuestos["sin_presupuesto"][:5]:
                print(f"     {s_['etiqueta']:45} {s_['gasto']:>8.2f}€")

        hitos = goal_rows(db, year, month)
        if hitos:
            print("\nHitos del mes:")
            for h in hitos:
                actual = "sin datos" if h["actual"] is None else f"{h['actual']:.2f} {h['unidad']}"
                print(f"  [{h['estado']:>10}] {h['titulo']:40} {actual:>14}  (objetivo {h['etiqueta_objetivo']})")

        hormiga = hormiga_service.resumen(db, year, month)
        if hormiga["num"] or hormiga["media_mensual"]:
            print(
                f"\nGastos hormiga (≤{hormiga['importe_max']:.0f}€): {hormiga['num']} compras, "
                f"{hormiga['total']:.2f}€ | media {hormiga['media_mensual']:.2f}€/mes "
                f"= {hormiga['anual']:.0f}€/año"
            )
            for c in hormiga["comercios"][:3]:
                print(f"    {c['num']:3} x {c['total']:>8.2f}€  {c['nombre']}")

        hoy = date.today()
        if (year, month) == (hoy.year, hoy.month):
            d = disponible_service.disponible(db, hoy)
            print(
                f"\nDisponible hoy: saldo {d['saldo']:.2f}€ - comprometido {d['comprometido']:.2f}€ "
                f"= libre {d['libre']:.2f}€ hasta el {d['ciclo']['siguiente']:%d/%m} "
                f"({d['libre_por_dia']:.2f}€/día, presupuesto de {d['mes_presupuesto_nombre']})"
            )
            l = libertad_service.resumen(db, hoy)
            colchon = f"{l['meses_colchon']:.1f}" if l["meses_colchon"] is not None else "?"
            tasa = f"{l['tasa_ahorro']:.0f}%" if l["tasa_ahorro"] is not None else "?"
            print(
                f"Base: colchón {colchon}/{l['meses_colchon_objetivo']} meses | deuda de consumo "
                f"{l['total_deuda_consumo']:.0f}€ | tasa de ahorro {tasa} ({l['meses_media']} meses) "
                f"| libertad financiera {l['progreso_fi']:.1f}% de {l['numero_fi']:.0f}€"
            )

        print("\nConsejos automáticos:")
        advices = get_advice(db, year, month)
        if not advices:
            print("  (sin avisos este mes)")
        for a in advices:
            print(f"  [{a.severity}] {a.title}: {a.message}")

        total = db.query(Transaction).count()
        sin = db.query(Transaction).filter(Transaction.category_id.is_(None)).count()
        print(f"\nSin clasificar: {sin}/{total} ({sin/total*100:.1f}%)" if total else "\nSin movimientos.")
        if sin:
            rows = (
                db.query(Transaction.description_raw, func.count(Transaction.id), func.sum(Transaction.amount))
                .filter(Transaction.category_id.is_(None))
                .group_by(Transaction.description_raw)
                .order_by(func.count(Transaction.id).desc())
                .limit(5)
                .all()
            )
            for desc, count, s in rows:
                print(f"    {count:3} x {s:>9.2f}€  {desc}")

        print("\nÚltimas notas:")
        notas = db.query(FinancialNote).order_by(FinancialNote.created_at.desc()).limit(3).all()
        if not notas:
            print("  (sin notas todavía)")
        for n in notas:
            print(f"  [{n.created_at.strftime('%d/%m/%Y')}] {n.title}")
    finally:
        db.close()


if __name__ == "__main__":
    today = date.today()
    year = int(sys.argv[1]) if len(sys.argv) > 1 else today.year
    month = int(sys.argv[2]) if len(sys.argv) > 2 else today.month
    main(year, month)
