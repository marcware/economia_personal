from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.advisor.engine import get_advice
from app.database import get_db
from app.services.dashboard_service import MONTHS_ES, available_months
from app.templating import templates

router = APIRouter(prefix="/consejos", tags=["consejos"])


@router.get("", response_class=HTMLResponse)
def consejos_home(
    request: Request, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)
) -> HTMLResponse:
    months_available = available_months(db)
    if not months_available:
        return templates.TemplateResponse(request, "advice.html", {"sin_datos": True})

    if year is None or month is None or (year, month) not in months_available:
        year, month = months_available[0]

    advices = get_advice(db, year, month)
    return templates.TemplateResponse(
        request,
        "advice.html",
        {
            "sin_datos": False,
            "year": year,
            "month": month,
            "month_name": MONTHS_ES[month],
            "advices": advices,
        },
    )
