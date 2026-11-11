"""Cliente HTTP mínimo para la API de Bit2Me (solo lectura).

Autenticación por petición: cabeceras `x-api-key`, `x-nonce` (milisegundos, creciente) y
`api-signature` = base64(HMAC-SHA512(secret, SHA256("nonce:ruta[?query]"))). Es el mismo
esquema que usa el servidor MCP oficial de Bit2Me (github.com/bit2me-devs/bit2me-mcp).
Los precios (/v3/currency/ticker) son públicos y no necesitan firma.
"""

import base64
import hashlib
import hmac
import time

import httpx

from app.config import settings


class Bit2MeConfigError(RuntimeError):
    pass


def firma(nonce: int, ruta: str, secret: str) -> str:
    resumen = hashlib.sha256(f"{nonce}:{ruta}".encode()).digest()
    return base64.b64encode(hmac.new(secret.encode(), resumen, hashlib.sha512).digest()).decode()


def configurado() -> bool:
    return bool(settings.bit2me_api_key and settings.bit2me_api_secret)


def _lista(respuesta) -> list[dict]:
    """Unos endpoints devuelven la lista tal cual y otros dentro de {"data": [...]}."""
    if isinstance(respuesta, dict):
        respuesta = respuesta.get("data", [])
    return [r for r in respuesta if isinstance(r, dict)] if isinstance(respuesta, list) else []


class Bit2MeClient:
    def __init__(self) -> None:
        if not configurado():
            raise Bit2MeConfigError("Faltan BIT2ME_API_KEY / BIT2ME_API_SECRET en .env")
        self.api_key = settings.bit2me_api_key
        self.secret = settings.bit2me_api_secret
        self.base_url = settings.bit2me_api_base.rstrip("/")
        self._ultimo_nonce = 0

    def _nonce(self) -> int:
        # Dos peticiones en el mismo milisegundo con el mismo nonce las rechaza con 401.
        self._ultimo_nonce = max(int(time.time() * 1000), self._ultimo_nonce + 1)
        return self._ultimo_nonce

    def get(self, ruta: str):
        nonce = self._nonce()
        headers = {
            "x-api-key": self.api_key,
            "x-nonce": str(nonce),
            "api-signature": firma(nonce, ruta, self.secret),
        }
        with httpx.Client(timeout=20) as client:
            r = client.get(f"{self.base_url}{ruta}", headers=headers)
        if r.status_code in (401, 403):
            raise Bit2MeConfigError(f"Bit2Me rechaza la API key ({r.status_code}): {r.text[:200]}")
        r.raise_for_status()
        return r.json()

    def saldos(self) -> tuple[dict[str, float], list[str]]:
        """Cantidad por moneda sumando wallet (pockets), Earn y Pro, y avisos de los
        servicios que no han respondido. El wallet es obligatorio (si falla, la clave no
        vale); Earn y Pro pueden no estar activados en la cuenta y se saltan."""
        fuentes = (
            ("/v1/wallet/pocket", "balance", "Wallet"),
            ("/v2/earn/wallets", "totalBalance", "Earn"),
            ("/v1/trading/wallet/balance", "balance", "Pro"),
        )
        cantidades: dict[str, float] = {}
        avisos = []
        for i, (ruta, campo, servicio) in enumerate(fuentes):
            try:
                filas = _lista(self.get(ruta))
            except (Bit2MeConfigError, httpx.HTTPError) as exc:
                if i == 0:
                    raise
                avisos.append(f"{servicio}: {exc}")
                continue
            for fila in filas:
                simbolo = (fila.get("currency") or "").upper()
                cantidad = float(fila.get(campo) or fila.get("balance") or 0)
                if simbolo and cantidad > 0:
                    cantidades[simbolo] = cantidades.get(simbolo, 0.0) + cantidad
        return cantidades, avisos

    def _todas(self, ruta: str, por_pagina: int = 100) -> list[dict]:
        filas: list[dict] = []
        while True:
            pagina = _lista(self.get(f"{ruta}?limit={por_pagina}&offset={len(filas)}"))
            filas += pagina
            if len(pagina) < por_pagina:
                return filas

    def operaciones(self) -> list[dict]:
        """Historial completo del wallet: depósitos, compras, ventas, pasos a Earn/Pro."""
        return self._todas("/v2/wallet/transaction")

    def trades_pro(self) -> list[dict]:
        """Compras y ventas ejecutadas en Bit2Me Pro (no salen en el historial del wallet)."""
        return self._todas("/v1/trading/trade")

    def precio_eur(self, simbolo: str) -> float | None:
        """Precio actual en euros; None si Bit2Me no tiene cotización para esa moneda."""
        if simbolo == "EUR":
            return 1.0
        with httpx.Client(timeout=20) as client:
            r = client.get(f"{self.base_url}/v3/currency/ticker/{simbolo}", params={"rateCurrency": "EUR"})
        if r.status_code != 200:
            return None
        filas = (r.json().get("EUR") or {}).get(simbolo) or []
        try:
            return float(filas[0]["price"])
        except (IndexError, KeyError, TypeError, ValueError):
            return None
