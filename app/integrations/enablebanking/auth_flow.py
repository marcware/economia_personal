"""Flujo de autorización AIS: /aspsps -> /auth (redirect) -> callback -> /sessions."""

import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.integrations.enablebanking.client import EnableBankingClient


def start_authorization(
    client: EnableBankingClient,
    aspsp_name: str,
    aspsp_country: str,
    psu_type: str = "personal",
    valid_days: int = 90,
) -> dict:
    """Inicia la autorización. Devuelve {"url", "state", "authorization_id"}."""
    state = str(uuid.uuid4())
    valid_until = (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat()
    body = {
        "access": {"valid_until": valid_until},
        "aspsp": {"name": aspsp_name, "country": aspsp_country},
        "state": state,
        "redirect_url": settings.enablebanking_redirect_url,
        "psu_type": psu_type,
    }
    response = client.post("/auth", json=body)
    response.raise_for_status()
    data = response.json()
    return {"url": data["url"], "state": state, "authorization_id": data.get("authorization_id")}


def create_session(client: EnableBankingClient, code: str) -> dict:
    """Canjea el `code` del callback por una sesión autorizada con sus cuentas."""
    response = client.post("/sessions", json={"code": code})
    response.raise_for_status()
    return response.json()
