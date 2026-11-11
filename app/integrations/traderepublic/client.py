"""Lectura de Trade Republic con pytr (su API privada; versión fijada y revisada en
pyproject.toml: el PIN solo viaja a api.traderepublic.com).

Solo lectura: `Lector` deja pasar únicamente las consultas de LECTURAS. pytr también sabe
comprar, vender, retirar dinero o tocar planes de ahorro, y nada de eso se puede llamar
desde aquí.

Login (v2, el de la web): se envían teléfono y PIN, Trade Republic pide confirmarlo en la
app del móvil y la sesión se guarda en secrets/ (cookies). Mientras dure, se lee sin pedir
nada; cuando caduca hay que volver a confirmar en el móvil.
"""

import asyncio

from pytr.api import TradeRepublicApi

from app.config import settings

LECTURAS = {
    "compact_portfolio", "cash", "instrument_details", "ticker", "timeline_transactions",
    "recv", "unsubscribe", "close", "resume_websession",
}


class TRConfigError(RuntimeError):
    pass


class TRSesionCaducada(RuntimeError):
    pass


def configurado() -> bool:
    return bool(settings.traderepublic_phone and settings.traderepublic_pin)


def _api() -> TradeRepublicApi:
    if not configurado():
        raise TRConfigError("Faltan TRADEREPUBLIC_PHONE / TRADEREPUBLIC_PIN en .env")
    settings.traderepublic_cookies_path.parent.mkdir(parents=True, exist_ok=True)
    return TradeRepublicApi(
        phone_no=settings.traderepublic_phone, pin=settings.traderepublic_pin,
        save_cookies=True, cookies_file=settings.traderepublic_cookies_path, use_v2_login=True,
    )


class Lector:
    """Envoltorio de solo lectura sobre una sesión ya iniciada."""

    def __init__(self, api: TradeRepublicApi) -> None:
        self._api = api

    def __getattr__(self, nombre):
        if nombre not in LECTURAS:
            raise AttributeError(f"{nombre}: solo se permiten lecturas en Trade Republic")
        return getattr(self._api, nombre)


def lector() -> Lector:
    api = _api()
    if not api.resume_websession():
        raise TRSesionCaducada("La sesión de Trade Republic ha caducado: vuelve a conectar desde la app")
    return Lector(api)


def sesion_activa() -> bool:
    if not configurado() or not settings.traderepublic_cookies_path.exists():
        return False
    try:
        return _api().resume_websession()
    except Exception:  # noqa: BLE001
        return False


# El login son dos peticiones (enviar el PIN, luego esperar la confirmación del móvil), así
# que el proceso de login vive en memoria entre ambas. Es una app de un solo usuario.
_login_en_curso: TradeRepublicApi | None = None


def iniciar_login() -> dict:
    """Envía teléfono y PIN. Devuelve si hace falta código de una app autenticadora."""
    global _login_en_curso
    api = _api()
    segundos = api.initiate_weblogin()
    _login_en_curso = api
    return {"segundos": segundos, "necesita_codigo": api.weblogin_needs_authenticator}


def completar_login(codigo: str | None = None) -> None:
    """Espera a que se confirme en el móvil (o usa el código del autenticador) y guarda la sesión."""
    global _login_en_curso
    if _login_en_curso is None:
        raise RuntimeError("No hay ningún login en curso: empieza de nuevo")
    try:
        _login_en_curso.complete_weblogin(codigo or None)
    finally:
        _login_en_curso = None


async def _recibir(tr: Lector, n: int) -> dict:
    respuestas = {}
    while len(respuestas) < n:
        sub_id, sub, resp = await tr.recv()
        respuestas[sub["type"]] = resp
        await tr.unsubscribe(sub_id)
    return respuestas


async def _leer(tr: Lector) -> dict:
    from pytr.tickers import fetch_instrument_details, fetch_tickers

    await tr.compact_portfolio()
    await tr.cash()
    r = await _recibir(tr, 2)
    posiciones = []
    for cat in r["compactPortfolioByType"].get("categories", []):
        for pos in cat.get("positions", []):
            pos.setdefault("instrumentId", pos.get("isin"))
            posiciones.append(pos)
    await fetch_instrument_details(tr, posiciones)
    await fetch_tickers(tr, posiciones)

    movimientos = []
    await tr.timeline_transactions()
    while True:
        _, sub, resp = await tr.recv()
        if sub["type"] != "timelineTransactions":
            continue
        movimientos += resp.get("items", [])
        siguiente = (resp.get("cursors") or {}).get("after")
        if not siguiente:
            break
        await tr.timeline_transactions(siguiente)
    await tr.close()
    return {"posiciones": posiciones, "efectivo": r["cash"], "movimientos": movimientos}


def leer() -> dict:
    """Posiciones (con precio actual y precio medio de compra), efectivo y el historial."""
    return asyncio.run(_leer(lector()))
