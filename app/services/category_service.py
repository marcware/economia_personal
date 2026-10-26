from sqlalchemy.orm import Session

from app.categorization.engine import categorize_transaction
from app.models import AmountSign, CategorizationRule, Category, Transaction

LEARNED_RULE_PRIORITY = 50  # menor que las reglas semilla (100+): las aprendidas ganan


def assign_category(
    db: Session, transaction_id: int, category_id: int, apply_to_similar: bool = True
) -> int:
    """Asigna categoría a una transacción. Si apply_to_similar, crea (o reutiliza) una regla
    a partir de su descripción exacta y recategoriza otras transacciones 'sin clasificar' que
    coincidan. Devuelve cuántas transacciones adicionales quedaron recategorizadas."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None:
        raise ValueError(f"Transacción {transaction_id} no encontrada")

    category = db.get(Category, category_id)
    if category is None:
        raise ValueError(f"Categoría {category_id} no encontrada")

    transaction.category_id = category_id
    transaction.manually_categorized = True
    # En los dos sentidos: sacar un movimiento de "Traspaso entre cuentas" tiene que volver
    # a contarlo (si no, sigue oculto en /movimientos y fuera de todos los totales).
    transaction.is_transfer = category.is_transfer_category

    recategorized = 0
    if apply_to_similar:
        pattern = transaction.description_normalized
        existing_rule = (
            db.query(CategorizationRule)
            .filter_by(pattern=pattern, category_id=category_id, is_regex=False)
            .one_or_none()
        )
        if existing_rule is None:
            db.add(CategorizationRule(
                pattern=pattern,
                is_regex=False,
                amount_sign=AmountSign.ANY,
                category_id=category_id,
                priority=LEARNED_RULE_PRIORITY,
                created_from_correction=True,
                active=True,
            ))
            db.flush()

        pendientes = (
            db.query(Transaction)
            .filter(
                Transaction.category_id.is_(None),
                Transaction.description_normalized == pattern,
                Transaction.id != transaction.id,
            )
            .all()
        )
        for tx in pendientes:
            if categorize_transaction(db, tx):
                recategorized += 1

    db.commit()
    return recategorized
