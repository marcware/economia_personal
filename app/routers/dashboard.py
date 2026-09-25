from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.advisor.engine import get_advice
from app.database import get_db
from app.services import hormiga_service
from app.services.dashboard_service import available_months, evolution, monthly_summary
from app.templating import templates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_class=HTMLResponse)
def dashboard_home(
    request: Request, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    months_available = available_months(db)
    if not months_available:
        return templates.TemplateResponse(request, "dashboard.html", {"sin_datos": True})

    if year is None or month is None or (year, month) not in months_available:
        year, month = months_available[0]

    idx = months_available.index((year, month))
    prev_month = months_available[idx + 1] if idx + 1 < len(months_available) else None
    next_month = months_available[idx - 1] if idx > 0 else None

    summary = monthly_summary(db, year, month)
    trend = evolution(db, months=12)
    advices = get_advice(db, year, month)[:3]
    hormiga = hormiga_service.resumen(db, year, month)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "sin_datos": False,
            "summary": summary,
            "trend": trend,
            "prev_month": prev_month,
            "next_month": next_month,
            "top_categorias": summary["desglose_categorias"][:8],
            "advices": advices,
            "hormiga": hormiga,
        },
    )
