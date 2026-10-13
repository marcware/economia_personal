from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.routers import (
    advice,
    anual,
    budgets,
    categories,
    connections,
    dashboard,
    net_worth,
    notes,
    transactions,
    transfer_candidates,
)
from app.database import get_db
from app.services import budget_service, disponible_service, pendientes_service
from app.templating import templates

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Economía Personal")

app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

app.include_router(connections.router)
app.include_router(dashboard.router)
app.include_router(advice.router)
app.include_router(transactions.router)
app.include_router(notes.router)
app.include_router(transfer_candidates.router)
app.include_router(budgets.router)
app.include_router(categories.router)
app.include_router(net_worth.router)
app.include_router(anual.router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Portada "Hoy": cuánto es libre hasta la nómina, para decidir antes de comprar."""
    budget_service.ajustar_meses_abiertos(db)  # usa el presupuesto del mes del ciclo
    return templates.TemplateResponse(
        request,
        "home.html",
        {"d": disponible_service.disponible(db), "pendientes": pendientes_service.pendientes(db)},
    )


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}
