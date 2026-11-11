"""Lee Quanloop desde su web y lo guarda en /inversiones.

Semiautomático, como scripts/scrape_ing.py: abre Chrome con un perfil propio
(secrets/quanloop_chrome) y el login lo haces tú (enlace por email y confirmación en la app).
La contraseña nunca se guarda. Al llegar al panel, el script pide con tu misma sesión el
extracto completo de la cuenta, el informe de inversiones diarias (reparto por planes de
riesgo) y el panel (intereses por cobrar), los guarda y cierra el navegador.
Ver app/integrations/quanloop/cuenta.py.

Uso:
    python scripts/scrape_quanloop.py
"""

import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import Error, Response, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal  # noqa: E402
from app.integrations.quanloop import cuenta  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "secrets" / "quanloop_chrome"
INICIO = f"{cuenta.BASE}/en/dashboard"
ESPERA_MAX_MS = 10 * 60 * 1000

# Se ejecuta en la propia web de Quanloop: mismo origen, mismas cookies de tu sesión.
PEDIR = """async ([url, json]) => {
    const r = await fetch(url, {credentials: "include", headers: {Accept: json ? "application/json" : "text/html"}});
    if (!r.ok) throw new Error("HTTP " + r.status + " " + url);
    return json ? await r.json() : await r.text();
}"""


def main() -> None:
    PERFIL.mkdir(parents=True, exist_ok=True)
    dentro = False

    def al_responder(resp: Response) -> None:
        nonlocal dentro
        # El panel pide sus últimos movimientos nada más entrar: señal de sesión iniciada.
        if resp.status == 200 and resp.url.startswith(f"{cuenta.BASE}/int/account-statement"):
            dentro = True

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(str(PERFIL), channel="chrome", headless=False)
        contexto.on("response", al_responder)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(INICIO)
        print("Entra en Quanloop (enlace del email y confirmación en la app). Al llegar al panel se lee solo.", flush=True)

        espera = 0
        while not dentro and contexto.pages and espera < ESPERA_MAX_MS:
            try:
                contexto.pages[-1].wait_for_timeout(1000)
            except Error:
                pass
            espera += 1000
        if not dentro:
            print("No se ha llegado a entrar en Quanloop.")
            sys.exit(1)

        try:
            _leer(contexto)
        finally:
            try:
                contexto.close()
            except Error:
                pass


def _leer(contexto) -> None:
    pagina = next(pg for pg in reversed(contexto.pages) if "quanloop.com" in pg.url)
    hoy = date.today()
    print("Dentro. Leyendo extracto e informes...", flush=True)
    datos = {
        "extracto": pagina.evaluate(PEDIR, [f"/int/account-statement?start={cuenta.INICIO_HISTORICO}&end={hoy}"
                                            "&asc=true&page=1&pageSize=2147483647", True]),
        "informe": pagina.evaluate(PEDIR, ["/en/reports/daily-investments", False]),
        "panel": pagina.evaluate(PEDIR, ["/en/dashboard", False]),
    }
    db = SessionLocal()
    try:
        r = cuenta.guardar(db, datos)
    finally:
        db.close()
    print(f"Quanloop leído: {r['total']:.2f} € (saldo {r['saldo']:.2f} € + {r['pendiente']:.2f} € por cobrar), "
          f"{r['movimientos']} movimientos ({r['aportaciones_nuevas']} aportaciones nuevas), "
          f"{r['cobrado']:.2f} € de intereses cobrados.", flush=True)
    for aviso in r["avisos"]:
        print(f"  aviso: {aviso}", flush=True)


if __name__ == "__main__":
    main()
