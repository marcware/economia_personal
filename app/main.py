from datetime import date
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
    dinero,
    inversiones,
    net_worth,
    notes,
    transactions,
    transfer_candidates,
)
from app.database import get_db
from app.advisor.engine import get_advice
from app.services import budget_service, dinero_service, disponible_service, pendientes_service
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
app.include_router(inversiones.router)
app.include_router(anual.router)
app.include_router(dinero.router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """Portada "Hoy": cuánto es libre hasta la nómina, qué hay que hacer y los consejos que
    más importan."""
    budget_service.ajustar_meses_abiertos(db)  # usa el presupuesto del mes del ciclo
    hoy = date.today()
    return templates.TemplateResponse(
        request,
        "home.html",
        {"d": disponible_service.disponible(db, hoy), "pendientes": pendientes_service.pendientes(db),
         # Llenar el fondo de emergencia no corre prisa: ese traspaso solo sale en Mi patrimonio.
         "traspasos": [t for t in dinero_service.mi_dinero(db, hoy)["traspasos"] if t["rol"] != "NOMINA"],
         # Presupuestos superados e hitos ya están en "Qué hacer".
         "consejos": [a for a in get_advice(db, hoy.year, hoy.month)
                      if a.type not in ("presupuesto_categoria", "hito")][:3]},
    )


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}
