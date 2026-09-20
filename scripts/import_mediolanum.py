"""Importa manualmente un extracto XLS de Mediolanum (solución temporal, ver
app/importers/mediolanum.py). Idempotente: reimportar el mismo fichero no duplica.

Uso:
    python scripts/import_mediolanum.py data/mediolanum.26/tmp660163611.xls
"""

import hashlib
import json
import sys
from decimal import Decimal

from sqlalchemy.orm import Session

from app.categorization.engine import categorize_transaction
from app.categorization.normalize import normalize_description
from app.database import SessionLocal
from app.importers.mediolanum import parse_mediolanum_xls
from app.models import Account, Bank, Transaction, TransactionSource
from app.services.transfer_detector import find_candidates


def get_or_create_mediolanum_account(db: Session) -> Account:
    account = db.query(Account).filter_by(bank=Bank.MEDIOLANUM).first()
    if account is None:
        account = Account(bank=Bank.MEDIOLANUM, name="Mediolanum", currency="EUR")
        db.add(account)
        db.flush()
    return account


def main(file_path: str) -> None:
    db = SessionLocal()
    try:
        account = get_or_create_mediolanum_account(db)
        raw_transactions = parse_mediolanum_xls(file_path)

        occurrence_counts: dict[tuple, int] = {}
        inserted = duplicated = categorized = 0

        for tx in raw_transactions:
            description_normalized = normalize_description(tx["description"])
            key = (account.id, tx["date"], tx["amount"], description_normalized)
            occurrence_counts[key] = occurrence_counts.get(key, 0) + 1
            occurrence_index = occurrence_counts[key]

            fingerprint_source = (
                f"{account.id}|{tx['date'].isoformat()}|{tx['amount']}|"
                f"{description_normalized}|{occurrence_index}"
            )
            fingerprint = hashlib.sha256(fingerprint_source.encode()).hexdigest()

            if db.query(Transaction).filter_by(fingerprint=fingerprint).one_or_none() is not None:
                duplicated += 1
                continue

            transaction = Transaction(
                account_id=account.id,
                date=tx["date"],
                amount=Decimal(str(tx["amount"])),
                currency="EUR",
                description_raw=tx["description"],
                description_normalized=description_normalized,
                source=TransactionSource.MANUAL,
                fingerprint=fingerprint,
                source_row_raw=json.dumps({k: str(v) for k, v in tx.items()}, ensure_ascii=False),
            )
            db.add(transaction)
            db.flush()
            if categorize_transaction(db, transaction):
                categorized += 1
            inserted += 1

        db.commit()
        nuevos_candidatos = find_candidates(db)
        print(
            f"Leídos: {len(raw_transactions)} | importados: {inserted} | "
            f"duplicados (ya existían): {duplicated} | categorizados: {categorized} | "
            f"nuevos candidatos a traspaso: {nuevos_candidatos}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/import_mediolanum.py <fichero.xls>")
        sys.exit(1)
    main(sys.argv[1])
