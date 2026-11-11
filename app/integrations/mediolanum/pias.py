"""PIAS de Mediolanum leído de su banca online (www.bmedonline.es), sin mirar la cuenta.

No hay API: se navega con Playwright dentro de la sesión que abre el usuario en
scripts/scrape_mediolanum.py (el login y la confirmación en el móvil son suyos; la
contraseña nunca se guarda). Una vez dentro:

- la portada (posición global) trae el saldo de cada póliza en el aria-label del enlace:
  "... PIAS ... Póliza: 121403606706 . Saldo 4.014 euros con 31 céntimos";
- al pulsar ese enlace la póliza queda seleccionada en la sesión, y su extracto está en
  basepage.aspx?a=2401 (formulario con periodo "Desde... Hasta...") y su cartera en a=2407.

El extracto lista, fondo a fondo, las suscripciones (lo que entra de cada prima, ya sin los
gastos de entrada) y los gastos de administración (participaciones que el seguro se cobra).
De ahí salen lo aportado, las participaciones de cada fondo y lo pagado en gastos.
"""

import hashlib
import html as html_lib
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Aportacion, ManualAssetEntry, Posicion
from app.services import inversiones_service

BASE = "https://www.bmedonline.es"
PROVEEDOR = "mediolanum"
NOMBRE = "PIAS Mediolanum"
AÑOS_MAX = 20  # hacia atrás, buscando el inicio de la póliza
AÑOS_VACIOS_PARA_PARAR = 2

SUSCRIPCION = "SUSCRIPCION"
GASTOS = "GASTOS DE ADMON."
ABONO = "ABONO"  # "ABONO FIDELIDAD MILL": participaciones regaladas por fidelidad


# --- Lectura del HTML (funciones puras) ---

def _num(texto: str) -> float:
    return float(texto.strip().replace(".", "").replace(",", "."))


def _texto(fragmento: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragmento))).strip()


def polizas(portada: str) -> list[dict]:
    """Pólizas PIAS de la posición global con su saldo."""
    resultado = []
    for etiqueta in re.findall(r'aria-label="([^"]*PIAS[^"]*)"', portada):
        etiqueta = html_lib.unescape(etiqueta)
        poliza = re.search(r"P[óo]liza:\s*(\d+)", etiqueta)
        saldo = re.search(r"Saldo\s+([\d.]+)\s+euros(?:\s+con\s+(\d+)\s+c[ée]ntimos)?", etiqueta)
        if poliza and saldo:
            resultado.append({
                "poliza": poliza.group(1),
                "saldo": _num(saldo.group(1)) + int(saldo.group(2) or 0) / 100,
            })
    return resultado


def extracto(pagina: str) -> list[dict]:
    """Filas de la tabla tblExtracto: fondo, fecha, concepto, participaciones, valor
    unitario e importe (negativo cuando sale)."""
    tabla = re.search(r'<table[^>]*id="tblExtracto".*?</table>', pagina, re.S | re.I)
    if not tabla:
        return []
    filas, fondo = [], None
    for fila in re.findall(r"<tr[^>]*>(.*?)</tr>", tabla.group(0), re.S | re.I):
        celdas = [_texto(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S | re.I)]
        if len(celdas) == 1 and celdas[0] and celdas[0] != "Consulta de extracto":
            fondo = celdas[0]
        elif len(celdas) == 5 and re.fullmatch(r"\d{2}/\d{2}/\d{4}", celdas[0]):
            filas.append({
                "fondo": fondo,
                "fecha": datetime.strptime(celdas[0], "%d/%m/%Y").date(),
                "concepto": celdas[1],
                "participaciones": _num(celdas[2]),
                "valor_unitario": _num(celdas[3]),
                "importe": _num(celdas[4]),
            })
    return filas


def _normaliza(concepto: str) -> str:
    sin_tildes = concepto.upper().replace("Ó", "O").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ú", "U")
    return re.sub(r"\s+", " ", sin_tildes).strip()


def calcular(saldo: float, filas: list[dict]) -> dict:
    """Aportaciones, fondos y gastos a partir del saldo y el extracto completo.

    Suscripción = dinero que entra en el fondo (+ participaciones). Cualquier otra fila con
    importe negativo saca participaciones (gastos, rescates). Lo aportado son las
    suscripciones menos los rescates; los gastos no son dinero que salga hacia ti, son coste.
    """
    aportaciones, avisos = [], []
    fondos: dict[str, dict] = {}
    gastos = 0.0
    for f in sorted(filas, key=lambda f: f["fecha"]):
        concepto = _normaliza(f["concepto"])
        fondo = fondos.setdefault(f["fondo"], {"participaciones": 0.0, "coste": 0.0, "gastos": 0.0, "regalado": 0.0, "precio": 0.0, "fecha": None})
        fondo["precio"], fondo["fecha"] = f["valor_unitario"], f["fecha"]
        clave = "|".join(str(f[k]) for k in ("fondo", "fecha", "concepto", "participaciones", "importe"))
        id_ = "pias-" + hashlib.sha1(clave.encode()).hexdigest()[:20]
        if concepto == SUSCRIPCION:
            fondo["participaciones"] += f["participaciones"]
            fondo["coste"] += f["importe"]
            aportaciones.append({"id": id_, "fecha": f["fecha"], "importe": f["importe"], "nota": f["fondo"]})
        elif concepto == GASTOS:
            fondo["participaciones"] -= f["participaciones"]
            fondo["gastos"] += -f["importe"]
            gastos += -f["importe"]
        elif concepto.startswith(ABONO):  # regalo de participaciones: entra sin coste
            fondo["participaciones"] += f["participaciones"]
            fondo["regalado"] += f["participaciones"]
        elif f["importe"] < 0:  # rescate u otra salida: dinero que vuelve a ti
            fondo["participaciones"] -= f["participaciones"]
            aportaciones.append({"id": id_, "fecha": f["fecha"], "importe": f["importe"], "nota": f"{f['concepto']} {f['fondo']}"})
            avisos.append(f"{f['fecha']:%d/%m/%Y} {f['concepto']} en {f['fondo']}: contado como dinero que sale")
        else:
            fondo["participaciones"] += f["participaciones"]
            avisos.append(f"{f['fecha']:%d/%m/%Y} {f['concepto']} en {f['fondo']}: concepto nuevo, solo suma participaciones")

    # Valor de cada fondo con el último precio visto, repartido para que sume el saldo real
    # (el extracto puede tener precios de hace semanas; el saldo de la portada es el de hoy).
    estimados = {n: max(d["participaciones"], 0) * d["precio"] for n, d in fondos.items()}
    total_estimado = sum(estimados.values())
    posiciones = []
    for nombre, d in fondos.items():
        if d["participaciones"] <= 1e-6:
            continue
        valor = saldo * estimados[nombre] / total_estimado if total_estimado > 0 else 0.0
        posiciones.append({
            "symbol": nombre[:20], "nombre": nombre, "cantidad": d["participaciones"],
            "precio": valor / d["participaciones"], "valor": round(valor, 2),
            # Los gastos se cobran en participaciones: son una pérdida ya cerrada, como una
            # venta. Así valor − aportado = (valor − coste) + realizado, sin restos.
            "coste": round(d["coste"] - d["gastos"], 2), "realizado": round(-d["gastos"], 2),
            "recompensas": d["regalado"],
        })
    return {"aportaciones": aportaciones, "posiciones": posiciones, "gastos": gastos, "avisos": avisos}


# --- Navegación (Playwright, dentro de la sesión ya iniciada por el usuario) ---

def leer(marco, hoy: date | None = None) -> dict:
    """Desde la portada de la banca: saldo, cartera (HTML, para revisar) y extracto completo.

    `marco` es el frame "area" del frameset de bmedonline.es, donde vive todo el contenido
    (la página de fuera está vacía). Cada clic es un postback de ASP.NET: se espera a que
    termine de navegar antes de leer.
    """
    hoy = hoy or date.today()
    portada = marco.content()
    encontradas = polizas(portada)
    if not encontradas:
        raise RuntimeError("No aparece ningún PIAS en la posición global")
    # El enlace es javascript:__doPostBack(...). Se ejecuta tal cual en vez de pulsarlo: al
    # entrar, Mediolanum a veces abre un aviso emergente encima que taparía el clic.
    accion = marco.locator("a[aria-label*='PIAS']").first.get_attribute("href") or ""
    if not accion.startswith("javascript:__doPostBack("):
        raise RuntimeError(f"Enlace del PIAS inesperado: {accion[:80]}")
    with marco.expect_navigation():
        marco.evaluate(accion.removeprefix("javascript:"))
    marco.goto(f"{BASE}/basepage.aspx?a=2407")
    cartera = marco.content()
    marco.goto(f"{BASE}/basepage.aspx?a=2401")

    filas, vacios = [], 0
    for año in range(hoy.year, hoy.year - AÑOS_MAX, -1):
        marco.select_option("select[name$='cboPeriodo']", "5")
        marco.fill("input[name$='txtFechaDesde']", f"01/01/{año}")
        marco.fill("input[name$='txtFechaHasta']", (hoy if año == hoy.year else date(año, 12, 31)).strftime("%d/%m/%Y"))
        with marco.expect_navigation():
            marco.click("input[name$='btnVer']")
        del_año = extracto(marco.content())
        filas += del_año
        vacios = 0 if del_año else vacios + 1
        if vacios >= AÑOS_VACIOS_PARA_PARAR and filas:
            break
    return {"poliza": encontradas[0]["poliza"], "saldo": encontradas[0]["saldo"], "filas": filas,
            "cartera_html": cartera}


# --- Guardado ---

def inversion(db: Session):
    return inversiones_service.inversion_de(db, PROVEEDOR, NOMBRE)


def guardar(db: Session, datos: dict) -> dict:
    calculo = calcular(datos["saldo"], datos["filas"])
    inv = inversion(db)
    ya = {e for (e,) in db.query(Aportacion.external_id).filter_by(inversion_id=inv.id)}
    nuevas = [a for a in calculo["aportaciones"] if a["id"] not in ya]
    for a in nuevas:
        db.add(Aportacion(inversion_id=inv.id, fecha=a["fecha"], importe=Decimal(str(round(a["importe"], 2))),
                          nota=a["nota"], external_id=a["id"]))
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    for p in calculo["posiciones"]:
        db.add(Posicion(
            inversion_id=inv.id, symbol=p["symbol"], nombre=p["nombre"], cantidad=Decimal(str(round(p["cantidad"], 6))),
            precio_eur=Decimal(str(round(p["precio"], 6))), valor_eur=Decimal(str(p["valor"])),
            coste_eur=Decimal(str(p["coste"])), realizado_eur=Decimal(str(p["realizado"])),
            recompensas=Decimal(str(round(p["recompensas"], 6))), recorded_at=ahora,
        ))
    db.add(ManualAssetEntry(name=inv.nombre, value=Decimal(str(round(datos["saldo"], 2))), liquido=False, recorded_at=ahora))
    db.commit()
    return {"saldo": datos["saldo"], "aportaciones_nuevas": len(nuevas), "movimientos": len(datos["filas"]),
            "gastos": calculo["gastos"], "avisos": calculo["avisos"]}
