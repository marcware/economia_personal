"""Descarga el extracto XLS de Mediolanum desde su banca online y lo importa.

El conector de Enable Banking para Mediolanum (beta) devuelve `server_error`, así que se
va por la web. Semiautomático a propósito: abre un Chrome visible con un perfil propio
(secrets/mediolanum_chrome, guarda la sesión entre usos) y el login lo haces tú — la
contraseña nunca se guarda y el banco pide confirmar en la app. Por ahora también la
descarga: ve a Movimientos, pide el extracto en Excel y el script lo recoge, lo guarda en
data/mediolanum/ y lo pasa a scripts/import_mediolanum.py (idempotente).

Cada URL visitada queda en secrets/mediolanum_rastro.txt: con ella se automatizará la
navegación hasta la descarga en la siguiente versión.

Uso:
    python scripts/scrape_mediolanum.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Download, Error, Page, sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "secrets" / "mediolanum_chrome"
RASTRO = RAIZ / "secrets" / "mediolanum_rastro.txt"
DESTINO = RAIZ / "data" / "mediolanum"
INICIO = "https://www.bancomediolanum.es/"
ESPERA_MAX_MS = 15 * 60 * 1000


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

        print("Entra en tu banca online, ve a Movimientos de la cuenta y descarga el extracto en Excel.")
        print("En cuanto llegue el fichero se importa y el navegador se cierra.")
        espera = 0
        try:
            while not descargados and espera < ESPERA_MAX_MS and contexto.pages:
                contexto.pages[0].wait_for_timeout(1000)
                espera += 1000
            contexto.close()
        except Error:
            pass  # cerraste el navegador a mano

    if not descargados:
        print("No ha llegado ningún extracto.")
        sys.exit(1)
    for ruta in descargados:
        subprocess.run([sys.executable, str(RAIZ / "scripts" / "import_mediolanum.py"), str(ruta)], check=True)


def _apuntar(url: str) -> None:
    with RASTRO.open("a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {url}\n")


if __name__ == "__main__":
    main()
