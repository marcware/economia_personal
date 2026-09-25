"""Sincroniza movimientos de todas las cuentas vinculadas.

Uso:
    python scripts/sync_accounts.py
"""

from app.database import SessionLocal
from app.integrations.enablebanking.client import EnableBankingClient
from app.integrations.enablebanking.sync_service import sync_account
from app.models import Account
from app.services import budget_service


def main() -> None:
    db = SessionLocal()
    client = EnableBankingClient()
    try:
        accounts = db.query(Account).all()
        if not accounts:
            print("No hay cuentas vinculadas todavía.")
            return
        for account in accounts:
            print(f"Sincronizando {account.bank.value} · {account.name} ({account.iban})...")
            try:
                result = sync_account(db, client, account)
                print(f"  -> {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"  -> ERROR: {exc}")
        # Con los movimientos nuevos, los presupuestos de los meses abiertos se ponen al día.
        budget_service.ajustar_meses_abiertos(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
