"""Reaplica las reglas de categorización sobre transacciones sin clasificar.

Útil tras añadir nuevas reglas semilla o tras una corrección manual masiva.

Uso:
    python scripts/recategorize.py
"""

from app.categorization.engine import categorize_transaction
from app.database import SessionLocal
from app.models import Transaction


def main() -> None:
    db = SessionLocal()
    try:
        pendientes = db.query(Transaction).filter(Transaction.category_id.is_(None)).all()
        categorizadas = 0
        for tx in pendientes:
            if categorize_transaction(db, tx):
                categorizadas += 1
        db.commit()
        print(f"Recategorizadas {categorizadas} de {len(pendientes)} transacciones pendientes.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
