"""Sesión de exploración de la banca online de Mediolanum, para automatizar la lectura del PIAS.

Abre el mismo Chrome que scripts/scrape_mediolanum.py (perfil en secrets/mediolanum_chrome).
Tú entras y navegas hasta tu PIAS; mientras, se guardan en secrets/mediolanum_exploracion/
las respuestas JSON y las páginas HTML que la web recibe del banco, y en trafico.txt la
lista de peticiones sin imágenes, estilos ni scripts. Nunca lo que tú envías (la contraseña
no se captura) y las respuestas de login/autenticación se descartan. Sirve para descubrir de qué
llamada sale el valor del PIAS y sus aportaciones. Cierra el navegador al terminar.

Uso:
    python scripts/explorar_mediolanum.py
"""

import json
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error, Response, sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
PERFIL = RAIZ / "secrets" / "mediolanum_chrome"
SALIDA = RAIZ / "secrets" / "mediolanum_exploracion"
INICIO = "https://www.bancomediolanum.es/"
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
        print("Entra en tu banca online y ve hasta tu PIAS (valor, aportaciones, movimientos).", flush=True)
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
