"""Cliente HTTP mínimo para la API de Enable Banking (AIS).

Autenticación: JWT firmado con RS256 usando la clave privada de la app,
con el application_id como `kid`. TTL máximo permitido por Enable Banking: 24h.
"""

import time

import httpx
import jwt

from app.config import settings


class EnableBankingConfigError(RuntimeError):
    pass


class EnableBankingClient:
    def __init__(self) -> None:
        if not settings.enablebanking_application_id or not settings.enablebanking_private_key_path:
            raise EnableBankingConfigError(
                "Faltan ENABLEBANKING_APPLICATION_ID / ENABLEBANKING_PRIVATE_KEY_PATH en .env"
            )
        if not settings.enablebanking_private_key_path.exists():
            raise EnableBankingConfigError(
                f"No se encuentra la clave privada en {settings.enablebanking_private_key_path}"
            )
        self.application_id = settings.enablebanking_application_id
        self._private_key = settings.enablebanking_private_key_path.read_text()
        self.base_url = settings.enablebanking_api_base.rstrip("/")

    def _build_jwt(self, ttl_seconds: int = 3600) -> str:
        now = int(time.time())
        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + ttl_seconds,
        }
        headers = {"typ": "JWT", "alg": "RS256", "kid": self.application_id}
        return jwt.encode(payload, self._private_key, algorithm="RS256", headers=headers)

    def _auth_headers(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._build_jwt()}"}
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def get(
        self, path: str, params: dict | None = None, extra_headers: dict[str, str] | None = None
    ) -> httpx.Response:
        with httpx.Client(timeout=30) as client:
            return client.get(f"{self.base_url}{path}", headers=self._auth_headers(extra_headers), params=params)

    def post(
        self, path: str, json: dict, extra_headers: dict[str, str] | None = None
    ) -> httpx.Response:
        with httpx.Client(timeout=30) as client:
            return client.post(f"{self.base_url}{path}", headers=self._auth_headers(extra_headers), json=json)

    def delete(self, path: str) -> httpx.Response:
        with httpx.Client(timeout=30) as client:
            return client.delete(f"{self.base_url}{path}", headers=self._auth_headers())

    def list_aspsps(self, country: str | None = None) -> list[dict]:
        params = {"country": country} if country else None
        response = self.get("/aspsps", params=params)
        response.raise_for_status()
        return response.json().get("aspsps", [])
