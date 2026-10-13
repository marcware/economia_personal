"""Sincroniza movimientos de todas las cuentas vinculadas.

Uso:
    python scripts/sync_accounts.py
"""

from app.database import SessionLocal
from app.integrations.enablebanking.client import EnableBankingClient
from app.integrations.enablebanking.sync_service import sync_all
from app.services import budget_service


def main() -> None:
    db = SessionLocal()
    client = EnableBankingClient()
    try:
        filas = sync_all(db, client)
        if not filas:
            print("No hay cuentas vinculadas todavía.")
            return
        for fila in filas:
            account = fila["cuenta"]
            print(f"{account.bank.value} · {account.name} ({account.iban})")
            print(f"  -> ERROR: {fila['error']}" if fila["error"] else f"  -> {fila['resultado']}")
        # Con los movimientos nuevos, los presupuestos de los meses abiertos se ponen al día.
        budget_service.ajustar_meses_abiertos(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
