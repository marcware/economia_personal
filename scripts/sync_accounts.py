"""Sincroniza movimientos de todas las cuentas vinculadas y, si hay clave, el valor de Bit2Me.

Uso:
    python scripts/sync_accounts.py
"""

from app.database import SessionLocal
from app.integrations.bit2me import client as bit2me_client
from app.integrations.bit2me import sync_service as bit2me_sync
from app.integrations.enablebanking.client import EnableBankingClient
from app.integrations.enablebanking.sync_service import sync_all
from app.services import budget_service


def main() -> None:
    db = SessionLocal()
    client = EnableBankingClient()
    try:
        if bit2me_client.configurado():
            try:
                r = bit2me_sync.sincronizar(db)
                print(f"Bit2Me: {r['total']:.2f} € en {r['monedas']} monedas")
                for aviso in r["avisos"]:
                    print(f"  aviso: {aviso}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                print(f"Bit2Me -> ERROR: {exc}")
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
