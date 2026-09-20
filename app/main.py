from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.routers import (
    advice,
    budgets,
    categories,
    connections,
    dashboard,
    net_worth,
    notes,
    transactions,
    transfer_candidates,
)
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html")


@app.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok"}
