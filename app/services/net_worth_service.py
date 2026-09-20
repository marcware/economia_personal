"""Patrimonio neto = saldos de cuentas (reales, vía API) + activos declarados a mano
(inversiones, cripto...) - pasivos declarados a mano (capital pendiente de deudas)."""

from sqlalchemy.orm import Session

from app.models import Account, AccountBalance, ManualAssetEntry, ManualLiabilityEntry


def latest_account_balances(db: Session) -> list[dict]:
    accounts = db.query(Account).all()
    result = []
    for acc in accounts:
        latest = (
            db.query(AccountBalance)
            .filter_by(account_id=acc.id)
            .order_by(AccountBalance.recorded_at.desc())
            .first()
        )
        if latest is not None:
            result.append({"account": acc, "balance": float(latest.balance), "recorded_at": latest.recorded_at})
    return result


def _latest_by_name(rows: list, value_attr: str) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in rows:
        if row.name not in seen:
            seen[row.name] = {"name": row.name, "value": float(getattr(row, value_attr)), "recorded_at": row.recorded_at}
    return list(seen.values())


def latest_manual_assets(db: Session) -> list[dict]:
    rows = db.query(ManualAssetEntry).order_by(ManualAssetEntry.recorded_at.desc()).all()
    return _latest_by_name(rows, "value")


def latest_manual_liabilities(db: Session) -> list[dict]:
    rows = db.query(ManualLiabilityEntry).order_by(ManualLiabilityEntry.recorded_at.desc()).all()
    return _latest_by_name(rows, "outstanding_balance")


def net_worth_summary(db: Session) -> dict:
    accounts = latest_account_balances(db)
    assets = latest_manual_assets(db)
    liabilities = latest_manual_liabilities(db)

    total_accounts = sum(a["balance"] for a in accounts)
    total_assets = sum(a["value"] for a in assets)
    total_liabilities = sum(l["value"] for l in liabilities)

    return {
        "accounts": accounts,
        "assets": assets,
        "liabilities": liabilities,
        "total_accounts": total_accounts,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_accounts + total_assets - total_liabilities,
    }
