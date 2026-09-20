from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Category, Transaction
from app.services.category_service import assign_category
from app.templating import templates

router = APIRouter(prefix="/movimientos", tags=["movimientos"])

PAGE_SIZE = 50


def _category_tree(db: Session) -> list[Category]:
    return db.query(Category).order_by(Category.parent_id.is_(None).desc(), Category.name).all()


@router.get("", response_class=HTMLResponse)
def movimientos_home(
    request: Request,
    categoria: str | None = None,
    cuenta: int | None = None,
    texto: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    query = db.query(Transaction).filter(Transaction.is_transfer.is_(False))

    if categoria == "sin_clasificar":
        query = query.filter(Transaction.category_id.is_(None))
    elif categoria:
        query = query.filter(Transaction.category_id == int(categoria))

    if cuenta:
        query = query.filter(Transaction.account_id == cuenta)

    if texto:
        query = query.filter(Transaction.description_raw.ilike(f"%{texto}%"))

    total = query.count()
    page = max(1, page)
    transactions = (
        query.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "transactions": transactions,
            "categories": _category_tree(db),
            "accounts": db.query(Account).all(),
            "categoria": categoria or "",
            "cuenta": cuenta,
            "texto": texto or "",
            "page": page,
            "total_pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "total": total,
        },
    )


@router.get("/agrupados", response_class=HTMLResponse)
def movimientos_agrupados(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    rows = (
        db.query(
            Transaction.description_normalized,
            func.count(Transaction.id),
            func.sum(Transaction.amount),
        )
        .filter(Transaction.category_id.is_(None))
        .group_by(Transaction.description_normalized)
        .order_by(func.count(Transaction.id).desc())
        .limit(150)
        .all()
    )
    grupos = [
        {"descripcion": desc, "count": count, "total": float(total)}
        for desc, count, total in rows
    ]
    return templates.TemplateResponse(
        request, "transactions_grouped.html", {"grupos": grupos, "categories": _category_tree(db)}
    )


@router.post("/categorizar")
def categorizar(
    transaction_id: int = Form(...),
    category_id: int = Form(...),
    apply_to_similar: bool = Form(False),
    redirect_to: str = Form("/movimientos"),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    assign_category(db, transaction_id, category_id, apply_to_similar)
    return RedirectResponse(redirect_to, status_code=302)


@router.post("/categorizar-grupo")
def categorizar_grupo(
    description_normalized: str = Form(...),
    category_id: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    primero = (
        db.query(Transaction)
        .filter(
            Transaction.category_id.is_(None),
            Transaction.description_normalized == description_normalized,
        )
        .first()
    )
    if primero:
        assign_category(db, primero.id, category_id, apply_to_similar=True)
    return RedirectResponse("/movimientos/agrupados", status_code=302)
