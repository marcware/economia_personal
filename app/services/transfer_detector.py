"""Detecta posibles traspasos entre las propias cuentas del usuario: misma cantidad con
signo opuesto, cuentas distintas, fecha cercana. No los excluye automáticamente — crea
un TransferCandidate en estado PENDING para que se confirmen o rechacen a mano.

Generaliza la búsqueda manual que se hizo para encontrar los autotraspasos ING<->Mediolanum
mal contados como ingreso/gasto real.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Transaction, TransferCandidate

MAX_DAYS_APART = 4


def find_candidates(db: Session) -> int:
    """Devuelve el número de candidatos nuevos creados."""
    already_flagged_ids = {
        row[0]
        for row in db.query(TransferCandidate.transaction_id).all()
    } | {
        row[0]
        for row in db.query(TransferCandidate.matched_transaction_id).all()
    }

    candidates = (
        db.query(Transaction)
        .filter(Transaction.is_transfer.is_(False))
        .order_by(Transaction.date)
        .all()
    )

    created = 0
    matched_this_run: set[int] = set()

    for tx in candidates:
        if tx.id in already_flagged_ids or tx.id in matched_this_run:
            continue

        match = (
            db.query(Transaction)
            .filter(
                Transaction.id != tx.id,
                Transaction.account_id != tx.account_id,
                Transaction.is_transfer.is_(False),
                Transaction.amount == -tx.amount,
                Transaction.date.between(
                    tx.date - timedelta(days=MAX_DAYS_APART), tx.date + timedelta(days=MAX_DAYS_APART)
                ),
            )
            .filter(~Transaction.id.in_(already_flagged_ids | matched_this_run))
            .first()
        )
        if match is None:
            continue

        days_apart = abs((match.date - tx.date).days)
        db.add(TransferCandidate(
            transaction_id=tx.id,
            matched_transaction_id=match.id,
            days_apart=days_apart,
        ))
        matched_this_run.add(tx.id)
        matched_this_run.add(match.id)
        created += 1

    db.commit()
    return created
