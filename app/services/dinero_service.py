"""Mi dinero (/dinero): dónde está cada euro y qué trabajo tiene.

Cada cuenta tiene un rol (Account.rol) y la Cuenta Naranja guarda las huchas:

- NOMINA (Mediolanum): cae la nómina y guarda el fondo de emergencia;
- RECIBOS: lo que falta por cobrarse de fijos e inversión hasta la próxima nómina;
- DIA: lo que falta por gastar de los variables del presupuesto hasta la próxima nómina;
- Cuenta Naranja: lo que debería haber hoy en las huchas (huchas_service);
- AHORRO: lo que queda, sin trabajo asignado todavía.

El cuadre es la suma de todas frente a esos trabajos: lo que sobra no tiene trabajo (se
puede invertir, amortizar...) y lo que falta es dinero comprometido que no está. Para cada
cuenta se dice cuánto le sobra o le falta, y de ahí los traspasos que lo dejan todo en su
sitio (siempre desde lo que sobra, empezando por la cuenta de ahorro).

El saldo de Mediolanum no llega por la conexión bancaria: es el del último extracto
importado (scripts/import_mediolanum.py), guardado como valor declarado ACTIVO_MEDIOLANUM.
"""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import Account, AccountBalance, Bank, Budget, BudgetGroup, ManualAssetEntry, RolCuenta
from app.services import disponible_service, huchas_service, libertad_service

ACTIVO_MEDIOLANUM = "Mediolanum (colchón, saldo cuenta)"
TRABAJO = {
    RolCuenta.NOMINA: "Nómina y fondo de emergencia",
    RolCuenta.RECIBOS: "Recibos fijos e inversión",
    RolCuenta.DIA: "Día a día: tarjeta y gastos variables",
    RolCuenta.AHORRO: "Ahorro sin asignar",
}
NOMBRE_BANCO = {Bank.ING: "ING", Bank.MEDIOLANUM: "Mediolanum"}
MESES_FONDO = 6  # como libertad_service.MESES_COLCHON_OBJETIVO
ORDEN = [RolCuenta.DIA, RolCuenta.RECIBOS, RolCuenta.NOMINA, RolCuenta.AHORRO]


def guardar_saldo_mediolanum(db: Session, filas: list[dict]) -> float | None:
    """Saldo de la cuenta de Mediolanum según el extracto: el de la fila más reciente (el
    extracto viene de la más nueva a la más vieja, así que en un mismo día manda la primera)."""
    con_saldo = [f for f in filas if f.get("balance") is not None]
    if not con_saldo:
        return None
    ultima = max(con_saldo, key=lambda f: f["date"])  # max devuelve la primera si hay empate
    db.add(ManualAssetEntry(name=ACTIVO_MEDIOLANUM, value=round(float(ultima["balance"]), 2), liquido=True,
                            recorded_at=datetime.combine(ultima["date"], datetime.min.time())))
    db.commit()
    return float(ultima["balance"])


def _saldo(db: Session, cuenta: Account) -> tuple[float | None, date | None]:
    if cuenta.rol == RolCuenta.NOMINA:
        fila = (db.query(ManualAssetEntry).filter_by(name=ACTIVO_MEDIOLANUM)
                .order_by(ManualAssetEntry.recorded_at.desc()).first())
        return (float(fila.value), fila.recorded_at.date()) if fila else (None, None)
    fila = (db.query(AccountBalance).filter_by(account_id=cuenta.id)
            .order_by(AccountBalance.recorded_at.desc()).first())
    return (float(fila.balance), fila.recorded_at.date()) if fila else (None, None)


def _variables_pendientes(db: Session, d: dict) -> float:
    """Lo que falta por gastar del presupuesto de variables (necesidades y deseos) en lo que
    queda de ciclo: lo que puede salir aún de la cuenta del día a día."""
    year, month = d["mes_presupuesto"]
    gastado = disponible_service._gastado_por_categoria(db, d["ciclo"]["inicio"], d["hoy"])
    total = 0.0
    for b in db.query(Budget).filter_by(active=True, year=year, month=month):
        if b.category.recurrente:
            continue
        total += max(float(b.monthly_limit) - gastado.get(b.category_id, 0.0), 0.0)
    return total


def fondo_objetivo(db: Session, year: int, month: int, recibos_anuales: float) -> float | None:
    """MESES_FONDO meses de necesidades según el presupuesto del mes (fijos y variables
    NECESIDAD más la cuota de recibos anuales): mira hacia delante, así que los préstamos
    ya pagados no lo inflan como la media de los últimos meses. None sin presupuesto."""
    limites = [float(b.monthly_limit) for b in db.query(Budget).filter_by(active=True, year=year, month=month)
               if b.category.budget_group == BudgetGroup.NECESIDAD]
    return (sum(limites) + recibos_anuales) * MESES_FONDO if limites else None


def mi_dinero(db: Session, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    d = disponible_service.disponible(db, hoy)
    h = huchas_service.huchas(db, hoy)
    # Con el presupuesto del mes que viene si ya está hecho: el fondo es para lo que llega.
    year, month = d["mes_presupuesto"]
    siguiente = (year + month // 12, month % 12 + 1)
    fondo = (fondo_objetivo(db, *siguiente, h["huchas"][0]["cuota"])
             or fondo_objetivo(db, year, month, h["huchas"][0]["cuota"]))
    if fondo is None:
        fondo = libertad_service.resumen(db, hoy)["objetivo_colchon"]

    objetivos = {
        RolCuenta.DIA: _variables_pendientes(db, d),
        RolCuenta.RECIBOS: d["total_fijos"] + d["inversion_pendiente"],
        RolCuenta.NOMINA: fondo,
        RolCuenta.AHORRO: None,
    }
    cuentas = []
    for cuenta in sorted(db.query(Account).filter(Account.rol.isnot(None)), key=lambda c: ORDEN.index(c.rol)):
        saldo, fecha = _saldo(db, cuenta)
        objetivo = objetivos[cuenta.rol]
        cuentas.append({
            "nombre": f"{NOMBRE_BANCO[cuenta.bank]} ···{cuenta.iban[-4:]}" if cuenta.iban else NOMBRE_BANCO[cuenta.bank],
            "rol": cuenta.rol.value, "trabajo": TRABAJO[cuenta.rol],
            "saldo": saldo, "fecha": fecha, "objetivo": objetivo,
            "diferencia": None if objetivo is None or saldo is None else saldo - objetivo,
        })
    cuentas.append({
        "nombre": f"ING {h['cuenta']}", "rol": "HUCHAS", "trabajo": "Huchas: recibos anuales, viajes e imprevistos",
        "saldo": h["saldo"], "fecha": h["fecha_saldo"], "objetivo": h["objetivo"],
        "diferencia": None if h["saldo"] is None else h["saldo"] - h["objetivo"],
    })

    total = sum(c["saldo"] or 0.0 for c in cuentas)
    con_trabajo = sum(c["objetivo"] for c in cuentas if c["objetivo"] is not None)
    sin_asignar = total - con_trabajo

    # Traspasos: a cada cuenta a la que le falta, desde las que tienen de más (primero la
    # de ahorro, que no tiene trabajo; luego lo que sobre en las demás).
    faltan = [c for c in cuentas if c["diferencia"] is not None and c["diferencia"] < -1]
    sobran = sorted([c for c in cuentas if c["rol"] == RolCuenta.AHORRO.value and (c["saldo"] or 0) > 0]
                    + [c for c in cuentas if c["diferencia"] is not None and c["diferencia"] > 1],
                    key=lambda c: c["rol"] != RolCuenta.AHORRO.value)
    disponibles = {id(c): (c["saldo"] if c["rol"] == RolCuenta.AHORRO.value else c["diferencia"]) for c in sobran}
    traspasos = []
    for destino in sorted(faltan, key=lambda c: c["diferencia"]):
        necesita = -destino["diferencia"]
        for origen in sobran:
            if necesita <= 0:
                break
            importe = min(necesita, disponibles[id(origen)])
            if importe >= 1:
                traspasos.append({"desde": origen["nombre"], "hacia": destino["nombre"],
                                  "para": destino["trabajo"].split(":")[0].lower(), "importe": round(importe, 2)})
                disponibles[id(origen)] -= importe
                necesita -= importe

    return {
        "hoy": hoy,
        "ciclo": d["ciclo"],
        "cuentas": cuentas,
        "total": total,
        "con_trabajo": con_trabajo,
        "sin_asignar": sin_asignar,
        "traspasos": traspasos,
        "huchas": h,
        "fondo_objetivo": fondo,
        "libre": d["libre"],
    }
