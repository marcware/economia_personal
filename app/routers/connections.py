import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.integrations.enablebanking.auth_flow import create_session, start_authorization
from app.integrations.enablebanking.client import EnableBankingClient, EnableBankingConfigError
from app.models import Account, Bank, BankConnection, ConnectionStatus
from app.templating import templates

router = APIRouter(prefix="/conexiones", tags=["conexiones"])
logger = logging.getLogger("conexiones")

# Claves cortas usadas en la URL -> datos reales del ASPSP en Enable Banking.
ASPSPS = {
    "ing": {"name": "ING", "country": "ES", "bank": Bank.ING},
    "mediolanum": {"name": "Banco Mediolanum", "country": "ES", "bank": Bank.MEDIOLANUM},
}


@router.get("", response_class=HTMLResponse)
def conexiones_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    connections = db.query(BankConnection).order_by(BankConnection.created_at.desc()).all()
    accounts = db.query(Account).order_by(Account.bank, Account.name).all()
    now = datetime.now(timezone.utc)
    return templates.TemplateResponse(
        request,
        "connections.html",
        {"connections": connections, "accounts": accounts, "aspsps": ASPSPS, "now": now},
    )


@router.get("/conectar/{aspsp_key}")
def conectar(aspsp_key: str) -> RedirectResponse:
    aspsp = ASPSPS.get(aspsp_key)
    if aspsp is None:
        raise HTTPException(status_code=404, detail="Banco no reconocido")
    try:
        client = EnableBankingClient()
    except EnableBankingConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result = start_authorization(client, aspsp["name"], aspsp["country"])
    return RedirectResponse(result["url"])


@router.get("/callback")
def callback(request: Request, code: str | None = None, error: str | None = None,
             error_description: str | None = None, state: str | None = None,
             db: Session = Depends(get_db)) -> RedirectResponse:
    if error:
        logger.error(
            "Callback con error del ASPSP/Enable Banking. query=%s error=%s error_description=%s state=%s",
            dict(request.query_params), error, error_description, state,
        )
        raise HTTPException(status_code=400, detail=f"{error}: {error_description}")
    if not code:
        raise HTTPException(status_code=400, detail="Falta el parámetro 'code' en el callback")

    client = EnableBankingClient()
    session_data = create_session(client, code)

    aspsp_name = session_data["aspsp"]["name"]
    aspsp_country = session_data["aspsp"]["country"]
    bank_enum = next((v["bank"] for v in ASPSPS.values() if v["name"] == aspsp_name), None)
    if bank_enum is None:
        raise HTTPException(status_code=400, detail=f"ASPSP no reconocido: {aspsp_name}")

    valid_until_raw = session_data.get("access", {}).get("valid_until")
    consent_valid_until = datetime.fromisoformat(valid_until_raw) if valid_until_raw else None

    connection = BankConnection(
        aspsp_name=aspsp_name,
        aspsp_country=aspsp_country,
        session_id=session_data["session_id"],
        consent_valid_until=consent_valid_until,
        status=ConnectionStatus.ACTIVE,
    )
    db.add(connection)

    for acc in session_data.get("accounts", []):
        identification_hash = acc.get("identification_hash")
        existing = None
        if identification_hash:
            existing = db.query(Account).filter_by(identification_hash=identification_hash).one_or_none()

        iban = (acc.get("account_id") or {}).get("iban")
        name = acc.get("name") or iban or "Cuenta"
        uid = acc.get("uid")

        if existing:
            existing.external_account_id = uid
            existing.iban = iban or existing.iban
        else:
            db.add(
                Account(
                    bank=bank_enum,
                    name=name,
                    currency="EUR",
                    external_account_id=uid,
                    iban=iban,
                    identification_hash=identification_hash,
                )
            )

    db.commit()
    return RedirectResponse("/conexiones", status_code=302)
