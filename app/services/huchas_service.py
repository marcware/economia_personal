"""Las huchas: dinero que se aparta cada mes para los pagos que no caben en un mes normal,
guardado fuera de la cuenta del día a día (en la Cuenta Naranja de ING). Son dos:

- recibos anuales (seguros, IBI, impuesto del coche, revisión del coche): se calcula sola
  con `anual_service.hucha_anual`; con la hucha ya llena basta la media mensual de los
  recibos de los próximos 12 meses;
- viajes e imprevistos (vacaciones, algo que se rompe): la cuota la decide el usuario
  (UserSettings.hucha_variable); se sugiere lo que costaron los últimos meses según
  `hucha_grandes` y `hucha_imprevistos`.

Cada una tiene una cuota mensual y lo que debería haber hoy (`inicial`): para los recibos,
lo justo para que con la cuota se llegue a cada uno a tiempo; para la variable, la avería
más cara vista, para que la próxima no pille a cero (los viajes se ahorran antes).
El saldo real es el de la Cuenta Naranja, que no da la conexión bancaria: se lee al entrar
en ING (scripts/scrape_ing.py) y se guarda como valor declarado con el nombre ACTIVO.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Account, Bank, ManualAssetEntry, Transaction, UserSettings
from app.services import anual_service

CUENTA = "Cuenta Naranja"
# Su valor declarado en /patrimonio (ya existía con este nombre antes de las huchas).
ACTIVO = "ING Cuenta Naranja (ahorro)"
NOMBRE_VARIABLE = "Viajes e imprevistos"
DIAS_PAREJA = 3  # entre la salida de un traspaso y su llegada a otra cuenta conectada


def saldo(db: Session) -> tuple[float | None, date | None]:
    fila = (db.query(ManualAssetEntry).filter_by(name=ACTIVO)
            .order_by(ManualAssetEntry.recorded_at.desc()).first())
    return (float(fila.value), fila.recorded_at.date()) if fila else (None, None)


def guardar_saldo(db: Session, valor: float) -> None:
    """Saldo de la Cuenta Naranja leído de la web de ING. No es líquido para el fondo de
    emergencia: todo él tiene dueño (las huchas)."""
    db.add(ManualAssetEntry(name=ACTIVO, value=round(valor, 2), liquido=False))
    db.commit()


def _inicial_recibos(hucha: dict, cuota: float) -> float:
    """Lo mínimo que tiene que haber hoy para que, sumando `cuota` cada mes, se llegue a
    cada recibo de los próximos 12 meses: max sobre k de (pagos hasta el mes k − k cuotas)."""
    acumulado, inicial = 0.0, 0.0
    for k, mes in enumerate(hucha["meses"], start=1):
        acumulado += mes["total"]
        inicial = max(inicial, acumulado - k * cuota)
    return inicial


def huchas(db: Session, hoy: date | None = None, tras: tuple[int, int] | None = None) -> dict:
    hoy = hoy or date.today()
    recibos = anual_service.hucha_anual(db, hoy, tras=tras)
    grandes = anual_service.hucha_grandes(db, hoy)
    imprevistos = anual_service.hucha_imprevistos(db, hoy)
    ajustes = db.get(UserSettings, 1)
    sugerida = grandes["aportacion"] + imprevistos["aportacion"]
    elegida = float(ajustes.hucha_variable) if ajustes and ajustes.hucha_variable is not None else None

    lista = [
        {"clave": "recibos", "nombre": "Recibos anuales", "ejemplo": "seguros, IBI, impuesto y revisión del coche",
         "cuota": recibos["media_mensual"], "inicial": _inicial_recibos(recibos, recibos["media_mensual"]),
         "detalle": recibos},
        {"clave": "variable", "nombre": NOMBRE_VARIABLE, "ejemplo": "vacaciones, algo que se rompe",
         "cuota": elegida if elegida is not None else sugerida, "elegida": elegida is not None,
         "sugerida": sugerida, "inicial": imprevistos["mayor"],
         "picos": sorted(grandes["picos"] + imprevistos["picos"], key=lambda p: -p["importe"]),
         "grandes": grandes, "imprevistos": imprevistos},
    ]
    en_cuenta, fecha = saldo(db)
    objetivo = sum(h["inicial"] for h in lista)
    return {
        "huchas": lista,
        "cuota": sum(h["cuota"] for h in lista),
        "objetivo": objetivo,
        "saldo": en_cuenta,
        "fecha_saldo": fecha,
        # Lo que hay que pasar de una vez para que las huchas arranquen con lo que les toca.
        "falta": max(objetivo - (en_cuenta or 0.0), 0.0),
        "cuenta": CUENTA,
    }


def fijar_variable(db: Session, cuota: float | None) -> None:
    ajustes = db.get(UserSettings, 1)
    if ajustes is None:
        ajustes = UserSettings(id=1)
        db.add(ajustes)
    ajustes.hucha_variable = round(cuota, 2) if cuota is not None else None
    db.commit()


def traspasado(db: Session, desde: date, hasta: date) -> float:
    """Dinero que ha ido de las cuentas conectadas a una cuenta propia que la app no ve (la
    Cuenta Naranja, incluido el redondeo de ING): traspasos de salida sin su entrada del mismo
    importe en otra cuenta de la app (las conectadas y la de Mediolanum)."""
    conectadas = [a.id for a in db.query(Account).filter(Account.bank != Bank.MEDIOLANUM)]
    salidas = (db.query(Transaction)
               .filter(Transaction.account_id.in_(conectadas), Transaction.is_transfer.is_(True),
                       # Solo traspasos: un recibo pagado por otro (dinero de paso) también
                       # puede ir marcado como movimiento entre cuentas.
                       Transaction.description_normalized.like("TRASPASO%"),
                       Transaction.amount < 0, Transaction.date.between(desde, hasta)).all())
    libres = (db.query(Transaction)
              .filter(Transaction.is_transfer.is_(True), Transaction.amount > 0,
                      Transaction.date.between(desde - timedelta(days=DIAS_PAREJA), hasta + timedelta(days=DIAS_PAREJA)))
              .all())
    total = 0.0
    for s in salidas:
        pareja = next((e for e in libres if e.amount == -s.amount and e.account_id != s.account_id
                       and abs((e.date - s.date).days) <= DIAS_PAREJA), None)
        if pareja is not None:
            libres.remove(pareja)
        else:
            total += -float(s.amount)
    return total
