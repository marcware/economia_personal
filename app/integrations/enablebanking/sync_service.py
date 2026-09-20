"""Trae movimientos reales desde Enable Banking y los guarda como Transaction,
con deduplicación idempotente y categorización automática."""

import hashlib
import json
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.categorization.engine import categorize_transaction
from app.categorization.normalize import normalize_description
from app.integrations.enablebanking.client import EnableBankingClient
from app.models import Account, AccountBalance, Transaction, TransactionSource
from app.services.transfer_detector import find_candidates

PREFERRED_BALANCE_TYPES = ("ITBD", "CLBD", "OTHR")


def fetch_and_store_balance(db: Session, client: EnableBankingClient, account: Account) -> Decimal | None:
    """Guarda una foto del saldo actual de la cuenta. Devuelve el importe o None si no
    se pudo obtener (p.ej. sesión caducada)."""
    if not account.external_account_id:
        return None
    response = client.get(f"/accounts/{account.external_account_id}/balances")
    if response.status_code != 200:
        return None
    balances = response.json().get("balances", [])
    if not balances:
        return None

    chosen = None
    for balance_type in PREFERRED_BALANCE_TYPES:
        chosen = next((b for b in balances if b.get("balance_type") == balance_type), None)
        if chosen:
            break
    chosen = chosen or balances[0]

    amount = Decimal(chosen["balance_amount"]["amount"])
    db.add(AccountBalance(
        account_id=account.id,
        balance=amount,
        currency=chosen["balance_amount"]["currency"],
    ))
    db.commit()
    return amount

# Sin date_from, la API de Enable Banking solo devuelve movimientos muy recientes
# (prácticamente ninguno). Para la primera sincronización pedimos histórico amplio;
# en sincronizaciones siguientes partimos del último movimiento ya guardado.
DEFAULT_BACKFILL_DAYS = 730
OVERLAP_DAYS = 3


def _parse_amount(tx: dict) -> Decimal:
    amount = Decimal(tx["transaction_amount"]["amount"])
    if tx["credit_debit_indicator"] == "DBIT":
        amount = -amount
    return amount


def _description(tx: dict) -> str:
    remittance = [r for r in (tx.get("remittance_information") or []) if r]
    if remittance:
        return " ".join(remittance)
    btc = tx.get("bank_transaction_code") or {}
    return btc.get("description") or "Movimiento sin descripción"


def _transaction_date(tx: dict) -> date_type:
    raw = tx.get("booking_date") or tx.get("transaction_date") or tx.get("value_date")
    return date_type.fromisoformat(raw)


def fetch_all_transactions(
    client: EnableBankingClient, account_uid: str, date_from: str | None = None
) -> list[dict]:
    transactions: list[dict] = []
    continuation_key: str | None = None
    while True:
        params: dict[str, str] = {}
        if date_from:
            params["date_from"] = date_from
        if continuation_key:
            params["continuation_key"] = continuation_key
        response = client.get(f"/accounts/{account_uid}/transactions", params=params)
        response.raise_for_status()
        data = response.json()
        transactions.extend(data.get("transactions", []))
        continuation_key = data.get("continuation_key")
        if not continuation_key:
            break
    return transactions


def sync_account(
    db: Session, client: EnableBankingClient, account: Account, date_from: str | None = None
) -> dict[str, int]:
    if not account.external_account_id:
        raise ValueError(f"La cuenta {account.name!r} no tiene external_account_id (¿conexión no activa?)")

    if date_from is None:
        last_date = db.query(func.max(Transaction.date)).filter_by(account_id=account.id).scalar()
        if last_date is not None:
            date_from = (last_date - timedelta(days=OVERLAP_DAYS)).isoformat()
        else:
            date_from = (date_type.today() - timedelta(days=DEFAULT_BACKFILL_DAYS)).isoformat()

    raw_transactions = fetch_all_transactions(client, account.external_account_id, date_from)

    occurrence_counts: dict[tuple, int] = {}
    inserted = 0
    duplicated = 0
    categorized = 0

    for tx in raw_transactions:
        amount = _parse_amount(tx)
        tx_date = _transaction_date(tx)
        description_raw = _description(tx)
        description_normalized = normalize_description(description_raw)
        external_id = tx.get("entry_reference") or tx.get("transaction_id")

        key = (account.id, tx_date, amount, description_normalized)
        occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
        occurrence_index = occurrence_counts[key]

        fingerprint_source = (
            f"{account.id}|{tx_date.isoformat()}|{amount}|{description_normalized}|{occurrence_index}"
        )
        fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()

        if db.query(Transaction).filter_by(fingerprint=fingerprint).one_or_none() is not None:
            duplicated += 1
            continue

        transaction = Transaction(
            account_id=account.id,
            date=tx_date,
            amount=amount,
            currency=tx["transaction_amount"]["currency"],
            description_raw=description_raw,
            description_normalized=description_normalized,
            source=TransactionSource.API_ENABLEBANKING,
            external_transaction_id=external_id,
            fingerprint=fingerprint,
            source_row_raw=json.dumps(tx, ensure_ascii=False),
        )
        db.add(transaction)
        db.flush()
        if categorize_transaction(db, transaction):
            categorized += 1
        inserted += 1

    db.commit()
    nuevos_candidatos = find_candidates(db)
    fetch_and_store_balance(db, client, account)

    return {
        "total_api": len(raw_transactions),
        "inserted": inserted,
        "duplicated": duplicated,
        "categorized": categorized,
        "nuevos_candidatos_traspaso": nuevos_candidatos,
    }
