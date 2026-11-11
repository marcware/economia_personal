"""Sincroniza movimientos de todas las cuentas vinculadas y las plataformas de inversión
con API configuradas (Bit2Me, Trade Republic).

Uso:
    python scripts/sync_accounts.py
"""

from app.database import SessionLocal
from app.integrations import plataformas
from app.integrations.enablebanking.client import EnableBankingClient
from app.integrations.enablebanking.sync_service import sync_all
from app.services import budget_service


def main() -> None:
    db = SessionLocal()
    client = EnableBankingClient()
    try:
        for f in plataformas.sincronizar_todas(db):
            if f["error"]:
                print(f"{f['nombre']} -> ERROR: {f['error']}")
                continue
            print(f"{f['nombre']}: {f['resultado']['total']:.2f} €")
            for aviso in f["resultado"]["avisos"]:
                print(f"  aviso: {aviso}")
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
