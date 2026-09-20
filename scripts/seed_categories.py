"""Inserta (si no existen ya) las categorías, subcategorías y reglas semilla.

Uso:
    python scripts/seed_categories.py
"""

from app.categorization.normalize import normalize_description
from app.categorization.seed_rules import CATEGORY_TREE, SEED_RULES
from app.database import SessionLocal
from app.models import CategorizationRule, Category, UserSettings


def seed() -> None:
    db = SessionLocal()
    try:
        parent_cache: dict[str, Category] = {}
        subcategory_cache: dict[tuple[str, str], Category] = {}

        for parent_name, sub_name, budget_group, is_transfer, recurrente, anual in CATEGORY_TREE:
            parent = parent_cache.get(parent_name)
            if parent is None:
                parent = db.query(Category).filter_by(name=parent_name, parent_id=None).one_or_none()
                if parent is None:
                    parent = Category(name=parent_name, parent_id=None, is_system=True)
                    db.add(parent)
                    db.flush()
                parent_cache[parent_name] = parent

            sub = db.query(Category).filter_by(name=sub_name, parent_id=parent.id).one_or_none()
            if sub is None:
                sub = Category(
                    name=sub_name,
                    parent_id=parent.id,
                    budget_group=budget_group,
                    is_system=True,
                    is_transfer_category=is_transfer,
                    recurrente=recurrente,
                    anual=anual,
                )
                db.add(sub)
                db.flush()
            subcategory_cache[(parent_name, sub_name)] = sub

        for pattern, is_regex, amount_sign, parent_name, sub_name, priority in SEED_RULES:
            category = subcategory_cache[(parent_name, sub_name)]
            normalized_pattern = normalize_description(pattern)
            exists = (
                db.query(CategorizationRule)
                .filter_by(pattern=normalized_pattern, category_id=category.id, amount_sign=amount_sign)
                .one_or_none()
            )
            if exists is None:
                db.add(
                    CategorizationRule(
                        pattern=normalized_pattern,
                        is_regex=is_regex,
                        amount_sign=amount_sign,
                        category_id=category.id,
                        priority=priority,
                        created_from_correction=False,
                        active=True,
                    )
                )

        if db.query(UserSettings).filter_by(id=1).one_or_none() is None:
            db.add(UserSettings(id=1))

        db.commit()
        n_categories = db.query(Category).count()
        n_rules = db.query(CategorizationRule).count()
        print(f"Seed aplicado: {n_categories} categorías, {n_rules} reglas.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
