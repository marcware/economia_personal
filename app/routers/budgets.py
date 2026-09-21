from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BudgetGroup, Category, GoalType, UserSettings
from app.services import budget_service, goal_service
from app.services.dashboard_service import MONTHS_ES
from app.templating import templates

router = APIRouter(prefix="/presupuestos", tags=["presupuestos"])


def _redirect(year: int, month: int) -> RedirectResponse:
    """Vuelve siempre al mes que se estaba editando, no al mes en curso."""
    return RedirectResponse(f"/presupuestos?year={year}&month={month}", status_code=302)


@router.get("", response_class=HTMLResponse)
def presupuestos_home(
    request: Request, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    meses = budget_service.selectable_months(db)
    hoy = date.today()
    if year is None or month is None or (year, month) not in meses:
        year, month = (hoy.year, hoy.month) if (hoy.year, hoy.month) in meses else meses[0]

    idx = meses.index((year, month))
    prev_month = meses[idx + 1] if idx + 1 < len(meses) else None
    next_month = meses[idx - 1] if idx > 0 else None

    resumen = budget_service.budget_summary(db, year, month)
    hitos = goal_service.goal_rows(db, year, month)
    gastos_anuales = budget_service.gastos_anuales(db, year)

    con_presupuesto = {f["budget"].category_id for f in resumen["filas"] if f["budget"] is not None}
    categorias_disponibles = [
        c
        for c in db.query(Category).filter(Category.parent_id.isnot(None)).order_by(Category.name).all()
        if c.id not in con_presupuesto
        and not c.is_transfer_category
        # Un presupuesto es un tope máximo: no tiene sentido "capar" el ahorro o la
        # inversión. Eso se fija como hito (INVERSION_MIN/AHORRO_MIN), en la sección
        # de abajo.
        and c.budget_group != BudgetGroup.AHORRO
    ]

    settings = db.query(UserSettings).filter_by(id=1).one_or_none() or UserSettings()

    return templates.TemplateResponse(
        request,
        "budgets.html",
        {
            "resumen": resumen,
            "hitos": hitos,
            "gastos_anuales": gastos_anuales,
            "categorias_disponibles": categorias_disponibles,
            "settings": settings,
            "year": year,
            "month": month,
            "month_name": MONTHS_ES[month],
            "prev_month": prev_month,
            "next_month": next_month,
            "meses_copiables": [m for m in meses if m != (year, month)],
            "meses_es": MONTHS_ES,
            "tipos_hito": [
                {"valor": t.value, "etiqueta": goal_service.GOAL_LABEL[t],
                 "necesita_categoria": t in goal_service.GOAL_NEEDS_CATEGORY}
                for t in GoalType
            ],
            "todas_categorias": db.query(Category).filter(Category.parent_id.isnot(None))
                                 .order_by(Category.name).all(),
        },
    )


@router.post("")
def crear_presupuesto(
    category_id: int = Form(...),
    monthly_limit: float = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Alta y edición: el upsert por (categoría, año, mes) sirve para las dos cosas."""
    budget_service.upsert_budget(db, category_id, year, month, monthly_limit)
    return _redirect(year, month)


@router.post("/copiar")
def copiar_presupuesto(
    origen_year: int = Form(...),
    origen_month: int = Form(...),
    destino_year: int = Form(...),
    destino_month: int = Form(...),
    sobrescribir: bool = Form(False),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    budget_service.copy_month(
        db, (origen_year, origen_month), (destino_year, destino_month), sobrescribir=sobrescribir
    )
    goal_service.copy_goals(db, (origen_year, origen_month), (destino_year, destino_month))
    return _redirect(destino_year, destino_month)


@router.post("/{budget_id}/eliminar")
def eliminar_presupuesto(
    budget_id: int, year: int = Form(...), month: int = Form(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    budget_service.deactivate_budget(db, budget_id)
    return _redirect(year, month)


@router.post("/ajustes")
def actualizar_ajustes(
    needs_pct: float = Form(...),
    wants_pct: float = Form(...),
    savings_pct: float = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = db.query(UserSettings).filter_by(id=1).one_or_none()
    if settings is None:
        settings = UserSettings(id=1)
        db.add(settings)
    settings.needs_pct = needs_pct
    settings.wants_pct = wants_pct
    settings.savings_pct = savings_pct
    db.commit()
    return _redirect(year, month)


@router.post("/hitos")
def crear_hito(
    goal_type: str = Form(...),
    target_amount: float = Form(...),
    year: int = Form(...),
    month: int = Form(...),
    category_id: int | None = Form(None),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    goal_service.upsert_goal(
        db, year, month, GoalType(goal_type), target_amount,
        category_id=category_id, title=(title or None),
    )
    return _redirect(year, month)


@router.post("/hitos/{goal_id}/eliminar")
def eliminar_hito(
    goal_id: int, year: int = Form(...), month: int = Form(...), db: Session = Depends(get_db)
) -> RedirectResponse:
    goal_service.deactivate_goal(db, goal_id)
    return _redirect(year, month)
