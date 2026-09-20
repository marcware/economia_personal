import re

from sqlalchemy.orm import Session

from app.models import AmountSign, CategorizationRule, Transaction


def categorize_transaction(db: Session, transaction: Transaction) -> bool:
    """Aplica la primera regla activa que coincida (por prioridad). Devuelve True si categorizó."""
    if transaction.category_id is not None:
        return False

    sign = AmountSign.POSITIVE if transaction.amount > 0 else AmountSign.NEGATIVE
    rules = (
        db.query(CategorizationRule)
        .filter_by(active=True)
        .order_by(CategorizationRule.priority.asc())
        .all()
    )

    for rule in rules:
        if rule.amount_sign != AmountSign.ANY and rule.amount_sign != sign:
            continue
        if rule.is_regex:
            matched = re.search(rule.pattern, transaction.description_normalized) is not None
        else:
            matched = rule.pattern in transaction.description_normalized
        if not matched:
            continue

        transaction.category_id = rule.category_id
        rule.match_count += 1
        if rule.category.is_transfer_category:
            transaction.is_transfer = True
        return True

    return False
