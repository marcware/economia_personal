"""Descarga el extracto XLS de Mediolanum desde su banca online y lo importa.

El conector de Enable Banking para Mediolanum (beta) devuelve `server_error`, así que se
va por la web. Semiautomático a propósito: abre un Chrome visible con un perfil propio
(secrets/mediolanum_chrome, guarda la sesión entre usos) y el login lo haces tú — la
contraseña nunca se guarda y el banco pide confirmar en la app. Por ahora también la
descarga: ve a Movimientos, pide el extracto en Excel y el script lo recoge, lo guarda en
data/mediolanum/ y lo pasa a scripts/import_mediolanum.py (idempotente).

Nada más entrar, y sin que hagas nada, lee también el PIAS (saldo y extracto completo; ver
app/integrations/mediolanum/pias.py) y lo guarda en /inversiones. Con --solo-pias cierra el
navegador después, sin esperar al extracto de la cuenta.

Cada URL visitada queda en secrets/mediolanum_rastro.txt.

Uso:
    python scripts/scrape_mediolanum.py [--solo-pias]
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Download, Error, Frame, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.database import SessionLocal  # noqa: E402
from app.integrations.mediolanum import pias  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "secrets" / "mediolanum_chrome"
RASTRO = RAIZ / "secrets" / "mediolanum_rastro.txt"
DESTINO = RAIZ / "data" / "mediolanum"
INICIO = "https://www.bancomediolanum.es/"
ESPERA_MAX_MS = 15 * 60 * 1000
CARTERA_PIAS = RAIZ / "secrets" / "mediolanum_pias_cartera.html"  # para mejorar la lectura


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    PERFIL.mkdir(parents=True, exist_ok=True)
    descargados: list[Path] = []

    def al_descargar(descarga: Download) -> None:
        sufijo = Path(descarga.suggested_filename).suffix or ".xls"
        ruta = DESTINO / f"extracto_{datetime.now():%Y-%m-%d_%H%M%S}{sufijo}"
        descarga.save_as(ruta)
        descargados.append(ruta)
        print(f"Descargado: {ruta}")

    def vigilar(page: Page) -> None:
        page.on("download", al_descargar)
        page.on("framenavigated", lambda frame: frame == page.main_frame and _apuntar(frame.url))

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            str(PERFIL), channel="chrome", headless=False, accept_downloads=True
        )
        contexto.on("page", vigilar)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        vigilar(pagina)
        pagina.goto(INICIO)

        solo_pias = "--solo-pias" in sys.argv
        print("Entra en tu banca online. Al entrar se lee el PIAS solo (no toques nada hasta que lo diga).", flush=True)
        espera, pias_leido = 0, False
        try:
            while not descargados and espera < ESPERA_MAX_MS and contexto.pages:
                if not pias_leido:
                    portada = _portada(contexto)
                    if portada is not None:
                        pias_leido = True
                        _leer_pias(portada)
                        if solo_pias:
                            break
                        print("Ahora, si quieres, ve a Movimientos de la cuenta y descarga el extracto en Excel.", flush=True)
                contexto.pages[-1].wait_for_timeout(1000)
                espera += 1000
            contexto.close()
        except Error:
            pass  # cerraste el navegador a mano

    if not descargados and pias_leido:
        return
    if not descargados:
        print("No ha llegado ningún extracto.")
        sys.exit(1)
    for ruta in descargados:
        subprocess.run([sys.executable, str(RAIZ / "scripts" / "import_mediolanum.py"), str(ruta)], check=True)


def _portada(contexto) -> Frame | None:
    """El marco con la posición global, una vez dentro de la banca. bmedonline.es es un
    frameset: el contenido está en el frame "area", no en la página."""
    for pagina in contexto.pages:
        for marco in pagina.frames:
            try:
                if "bmedonline.es" in marco.url and marco.locator("a[aria-label*='Póliza']").count():
                    return marco
            except Error:
                pass
    return None


def _leer_pias(marco: Frame) -> None:
    print("Dentro. Leyendo el PIAS, no toques nada...", flush=True)
    try:
        datos = pias.leer(marco)
    except Exception as exc:  # noqa: BLE001
        print(f"No se ha podido leer el PIAS: {exc}", flush=True)
        return
    CARTERA_PIAS.write_text(datos["cartera_html"])
    db = SessionLocal()
    try:
        r = pias.guardar(db, datos)
    finally:
        db.close()
    print(f"PIAS leído: saldo {r['saldo']:.2f} €, {r['movimientos']} movimientos del extracto "
          f"({r['aportaciones_nuevas']} aportaciones nuevas), gastos de administración {r['gastos']:.2f} €.", flush=True)
    for aviso in r["avisos"]:
        print(f"  aviso: {aviso}", flush=True)


def _apuntar(url: str) -> None:
    with RASTRO.open("a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {url}\n")


if __name__ == "__main__":
    main()
