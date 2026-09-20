from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.categorization.normalize import normalize_description
from app.database import get_db
from app.models import AmountSign, BudgetGroup, CategorizationRule, Category
from app.templating import templates

router = APIRouter(prefix="/categorias", tags=["categorias"])


@router.get("", response_class=HTMLResponse)
def categorias_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    parents = db.query(Category).filter_by(parent_id=None).order_by(Category.name).all()
    subcategories = db.query(Category).filter(Category.parent_id.isnot(None)).order_by(Category.name).all()

    rules_by_category: dict[int, list[CategorizationRule]] = {}
    for c in subcategories:
        rules_by_category[c.id] = (
            db.query(CategorizationRule).filter_by(category_id=c.id).order_by(CategorizationRule.priority).all()
        )

    return templates.TemplateResponse(
        request,
        "categories.html",
        {
            "parents": parents,
            "rules_by_category": rules_by_category,
            "all_subcategories": subcategories,
            "budget_groups": list(BudgetGroup),
            "amount_signs": list(AmountSign),
        },
    )


@router.post("/subcategoria")
def crear_subcategoria(
    parent_id: int = Form(...),
    name: str = Form(...),
    budget_group: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    bg = BudgetGroup(budget_group) if budget_group else None
    name = name.strip()
    exists = db.query(Category).filter_by(parent_id=parent_id, name=name).one_or_none()
    if exists is None:
        db.add(Category(parent_id=parent_id, name=name, budget_group=bg, is_system=False))
        db.commit()
    return RedirectResponse("/categorias", status_code=302)


@router.post("/regla")
def crear_regla(
    pattern: str = Form(...),
    category_id: int = Form(...),
    is_regex: bool = Form(False),
    amount_sign: str = Form("ANY"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    normalized = pattern.strip() if is_regex else normalize_description(pattern)
    db.add(CategorizationRule(
        pattern=normalized,
        is_regex=is_regex,
        amount_sign=AmountSign(amount_sign),
        category_id=category_id,
        priority=60,
        created_from_correction=True,
        active=True,
    ))
    db.commit()
    return RedirectResponse("/categorias", status_code=302)


@router.post("/regla/{rule_id}/activar")
def activar_regla(rule_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    rule = db.get(CategorizationRule, rule_id)
    if rule is not None:
        rule.active = True
        db.commit()
    return RedirectResponse("/categorias", status_code=302)


@router.post("/regla/{rule_id}/desactivar")
def desactivar_regla(rule_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    rule = db.get(CategorizationRule, rule_id)
    if rule is not None:
        rule.active = False
        db.commit()
    return RedirectResponse("/categorias", status_code=302)
