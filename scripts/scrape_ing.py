"""Lee el plan de pensiones de ING desde su web y lo guarda en /inversiones.

Semiautomático, como scripts/scrape_mediolanum.py: abre Chrome con un perfil propio
(secrets/ing_chrome) y el login lo haces tú (con la confirmación en el móvil). La contraseña
nunca se guarda. Nada más entrar, la web de ING pide tu posición global: el script la
recoge, pide los movimientos del plan con tu misma sesión, los guarda y cierra el navegador.
Ver app/integrations/ing/plan_pensiones.py.

Uso:
    python scripts/scrape_ing.py
"""

import re
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import Error, Response, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal  # noqa: E402
from app.integrations.ing import plan_pensiones  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "secrets" / "ing_chrome"
INICIO = "https://www.ing.es/"
ESPERA_MAX_MS = 10 * 60 * 1000
POSICION = re.compile(r"^https://api\.ing\.ingdirect\.es/position-keeping/?(\?|$)")
POR_PAGINA = 100

# Se ejecuta en la propia web de ING: mismo origen, mismas cookies de tu sesión.
PEDIR_JSON = """async (url) => {
    const r = await fetch(url, {credentials: "include", headers: {Accept: "application/json"}});
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
}"""


def main() -> None:
    PERFIL.mkdir(parents=True, exist_ok=True)
    capturado: dict = {}

    def al_responder(resp: Response) -> None:
        if resp.status == 200 and POSICION.match(resp.url):
            try:
                capturado["posicion"] = resp.json()
            except Error:
                pass

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(str(PERFIL), channel="chrome", headless=False)
        contexto.on("response", al_responder)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(INICIO)
        print("Entra en tu área de clientes de ING. Al entrar se lee el plan solo (no toques nada).", flush=True)

        espera = 0
        while "posicion" not in capturado and contexto.pages and espera < ESPERA_MAX_MS:
            try:
                contexto.pages[-1].wait_for_timeout(1000)
            except Error:
                pass
            espera += 1000
        if "posicion" not in capturado:
            print("No se ha llegado a entrar en ING.")
            sys.exit(1)

        try:
            _leer(contexto, capturado["posicion"])
        finally:
            try:
                contexto.close()
            except Error:
                pass


def _leer(contexto, posicion: dict) -> None:
    datos_plan = plan_pensiones.plan(posicion)
    if datos_plan is None:
        print("No aparece ningún plan de pensiones en tu posición global.")
        sys.exit(1)
    print(f"Dentro. {datos_plan['nombre']}: {datos_plan['saldo']:.2f} €. Leyendo movimientos...", flush=True)
    pagina = next(pg for pg in contexto.pages if "ingdirect.es" in pg.url)
    desde = date.fromisoformat(datos_plan["apertura"]) if datos_plan.get("apertura") else date(2000, 1, 1)
    movimientos: list[dict] = []
    while True:
        url = (f"/genoma_api/rest/products/{datos_plan['id']}/movements?limit={POR_PAGINA}"
               f"&offset={len(movimientos)}&fromDate={desde:%d/%m/%Y}&toDate={date.today():%d/%m/%Y}"
               "&filterEru=false&status=")
        respuesta = pagina.evaluate(PEDIR_JSON, url)
        lote = respuesta.get("elements") or []
        movimientos += lote
        if not lote or len(movimientos) >= (respuesta.get("total") or 0):
            break

    db = SessionLocal()
    try:
        r = plan_pensiones.guardar(db, {"plan": datos_plan, "movimientos": movimientos})
    finally:
        db.close()
    print(f"Plan leído: {r['saldo']:.2f} €, {r['movimientos']} movimientos ({r['aportaciones_nuevas']} aportaciones nuevas).",
          flush=True)
    for aviso in r["avisos"]:
        print(f"  aviso: {aviso}", flush=True)


if __name__ == "__main__":
    main()
