from dataclasses import dataclass

SEVERITY_ORDER = {"danger": 0, "warning": 1, "info": 2}


@dataclass
class Advice:
    type: str
    severity: str  # info | warning | danger
    title: str
    message: str
    url: str | None = None  # enlace de acción, p.ej. /presupuestos?year=2026&month=11
