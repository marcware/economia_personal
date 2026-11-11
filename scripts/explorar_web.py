"""Sesión de exploración de una web (banca online, plataforma de inversión) para automatizar
después su lectura, como se hizo con el PIAS de Mediolanum.

Abre Chrome con un perfil propio por sitio (secrets/<sitio>_chrome; el de mediolanum es el
mismo que usa scripts/scrape_mediolanum.py). Tú entras y navegas hasta lo que interese;
mientras, se guardan en secrets/<sitio>_exploracion/
las respuestas JSON y las páginas HTML que la web recibe del banco, y en trafico.txt la
lista de peticiones sin imágenes, estilos ni scripts. Nunca lo que tú envías (la contraseña
no se captura) y las respuestas de login/autenticación se descartan. Sirve para descubrir de qué
llamada salen los datos. Cierra el navegador al terminar.

Uso:
    python scripts/explorar_web.py <sitio> [url de inicio]
    python scripts/explorar_web.py mediolanum
    python scripts/explorar_web.py ing
    python scripts/explorar_web.py quanloop
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error, Response, sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
INICIOS = {
    "mediolanum": "https://www.bancomediolanum.es/",
    "ing": "https://www.ing.es/",
    "quanloop": "https://quanloop.com/en/login",
}
SITIO = sys.argv[1] if len(sys.argv) > 1 else "mediolanum"
INICIO = sys.argv[2] if len(sys.argv) > 2 else INICIOS[SITIO]
PERFIL = RAIZ / "secrets" / f"{SITIO}_chrome"
SALIDA = RAIZ / "secrets" / f"{SITIO}_exploracion"
# Analítica y publicidad: ruido que no lleva datos tuyos útiles.
RUIDO = re.compile(r"doubleclick|google|cookiebot|clarity\.ms|facebook|hotjar|adobe|demdex|omtrdc|tealium|criteo|bing\.com|/rb_", re.I)
ESPERA_MAX_MS = 20 * 60 * 1000
ESTATICOS = {"image", "stylesheet", "font", "media", "script"}
EXCLUIR = re.compile(r"login|logon|auth|token|password|credential|otp|sso", re.I)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    PERFIL.mkdir(parents=True, exist_ok=True)
    n = 0

    def al_responder(resp: Response) -> None:
        nonlocal n
        tipo = resp.request.resource_type
        if tipo in ESTATICOS:
            return
        url = resp.url
        if RUIDO.search(url):
            return
        contenido = resp.headers.get("content-type") or ""
        _apuntar(f"{resp.status} {resp.request.method} {tipo} {contenido.split(';')[0]} {url}")
        if EXCLUIR.search(url) or not ("json" in contenido or "html" in contenido or "xml" in contenido):
            return
        try:
            cuerpo = resp.text()
        except Exception:  # noqa: BLE001
            return
        n += 1
        extension = "json" if "json" in contenido else "html"
        nombre = f"{n:04d}_{re.sub(r'[^A-Za-z0-9]+', '_', url.split('?')[0])[-80:]}.{extension}"
        (SALIDA / nombre).write_text(f"<!-- {url} -->\n{cuerpo}" if extension == "html" else json.dumps(
            {"url": url, "status": resp.status, "cuerpo": _json(cuerpo)}, ensure_ascii=False, indent=1))

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(str(PERFIL), channel="chrome", headless=False)
        # En el contexto, no en una página: así se oye también a pestañas nuevas y marcos.
        contexto.on("response", al_responder)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        pagina.goto(INICIO)
        print(f"Entra en {SITIO} y ve hasta lo que quieras automatizar (valor, aportaciones, movimientos).", flush=True)
        print("Cuando hayas visto todo, cierra el navegador.", flush=True)
        # Sigue mientras quede alguna pestaña: cerrar la primera no termina la sesión.
        espera = 0
        while contexto.pages and espera < ESPERA_MAX_MS:
            try:
                contexto.pages[-1].wait_for_timeout(1000)
            except Error:
                pass  # esa pestaña se acaba de cerrar
            espera += 1000
        try:
            contexto.close()
        except Error:
            pass
    print(f"Guardadas {n} respuestas en {SALIDA}")


def _json(texto: str):
    try:
        return json.loads(texto)
    except ValueError:
        return texto


def _apuntar(linea: str) -> None:
    with (SALIDA / "trafico.txt").open("a") as f:
        f.write(f"{datetime.now():%H:%M:%S} {linea}\n")


if __name__ == "__main__":
    main()
