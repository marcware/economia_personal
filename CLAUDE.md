# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local personal-finance app (Spanish UI/comments). It pulls bank movements from ING (and manually from
Banco Mediolanum) via the [Enable Banking](https://enablebanking.com) Open Banking/PSD2 API — no manual
CSV exports — then provides a monthly income/expense dashboard by category and a rule-based "financial
coach" advice engine. Server-rendered with FastAPI + Jinja2 (no frontend framework/build step).

The project is under active construction; see the phase plan referenced in `README.md`
(`/home/marcware/.claude/plans/vale-mira-quiero-eh-cosmic-sloth.md`) for current status.

## Setup and running

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in Enable Banking credentials

uvicorn app.main:app --reload --port 8000 \
  --ssl-keyfile secrets/localhost.key --ssl-certfile secrets/localhost.crt
```

Then open https://localhost:8000. Enable Banking requires an HTTPS redirect URL even for a "Production"
app on localhost, so the dev server always runs over TLS using a self-signed cert at
`secrets/localhost.{key,crt}` (generated with OpenSSL, gitignored) — accept the browser warning once.

No test suite exists yet (`pytest`/`pytest-asyncio` are declared as dev dependencies but there are no
test files). No lint/format tooling is configured in `pyproject.toml`.

## Database and migrations

SQLite at `data/economia.db` (path from `Settings.database_path` in [app/config.py](app/config.py)).
Schema is managed with Alembic; `migrations/env.py` builds the DB URL from app settings rather than
`alembic.ini`, and imports `app.models` so autogenerate sees all tables via `Base.metadata`.

```bash
alembic upgrade head                          # apply migrations
alembic revision --autogenerate -m "mensaje"   # create a new migration
```

## Connecting a bank (Enable Banking / ING)

Credentials (`ENABLEBANKING_APPLICATION_ID`, `ENABLEBANKING_PRIVATE_KEY_PATH`) go in `.env`
(gitignored); the redirect URL `https://localhost:8000/conexiones/callback` must be registered in the
Enable Banking control panel. Auth is a signed RS256 JWT (app private key, `kid` = application_id, see
[app/integrations/enablebanking/client.py](app/integrations/enablebanking/client.py)). Consent from ING
must be renewed roughly every 90 days per PSD2. The connect/callback flow lives in
[app/routers/connections.py](app/routers/connections.py) +
[app/integrations/enablebanking/auth_flow.py](app/integrations/enablebanking/auth_flow.py); movement
sync in [app/integrations/enablebanking/sync_service.py](app/integrations/enablebanking/sync_service.py).

Banco Mediolanum has no Enable Banking coverage, so its movements are imported manually from an XLS
export via [app/importers/mediolanum.py](app/importers/mediolanum.py) and
[scripts/import_mediolanum.py](scripts/import_mediolanum.py) (idempotent — re-importing the same file
doesn't duplicate transactions).

## Architecture

Layout is a standard layered FastAPI app under `app/`:

- **models/** — SQLAlchemy ORM models (`Base` from [app/database.py](app/database.py)). `app/models/__init__.py`
  re-exports everything and is imported by `migrations/env.py` so autogenerate picks up all tables —
  add new models there too.
- **routers/** — one `APIRouter` per feature area (dashboard, transactions, budgets, categories,
  connections, advice, notes, net_worth, transfer_candidates), each mounted in [app/main.py](app/main.py).
  Routers call into `services/`/`advisor/`/`categorization/` and render Jinja2 templates from
  `app/templates/` via the shared `templates` instance in [app/templating.py](app/templating.py)
  (which also injects template globals, e.g. the pending-transfer-candidates nav badge).
- **services/** — cross-cutting business logic used by routers and scripts (dashboard aggregation,
  net worth, transfer-candidate detection between own accounts).
- **categorization/** — rule-based auto-categorization. [engine.py](app/categorization/engine.py)
  applies the highest-priority active `CategorizationRule` whose (normalized) description pattern
  matches and whose amount sign matches; [normalize.py](app/categorization/normalize.py) normalizes
  descriptions before matching; [seed_rules.py](app/categorization/seed_rules.py) defines the initial
  category tree and seed rules (loaded by [scripts/seed_categories.py](scripts/seed_categories.py)).
- **advisor/** — the "financial coach" advice engine. [engine.py](app/advisor/engine.py)'s `get_advice()`
  is the entrypoint: loads the month's transactions as a pandas DataFrame
  ([data.py](app/advisor/data.py)), then runs independent checks (`rule_50_30_20`, `budget_alerts`,
  `anomaly_and_savings`), merging and sorting results by severity (`SEVERITY_ORDER` in
  [types.py](app/advisor/types.py)). New advice checks should follow this same pattern: a pure function
  taking the DataFrame/db + settings and returning a list of `Advice`.
- **integrations/enablebanking/** — the Enable Banking API client and OAuth-style consent/session flow.
  `EnableBankingClient` ([client.py](app/integrations/enablebanking/client.py)) handles JWT auth and raw
  HTTP; `auth_flow.py` and `sync_service.py` build on top of it.
- **importers/** — one-off/manual file-based importers (currently Mediolanum XLS) for banks not
  reachable via Enable Banking.

`scripts/` holds standalone maintenance/reporting scripts run directly with `python scripts/<name>.py`
against a real `SessionLocal()` (seeding categories, bulk/re-categorization, account sync, monthly
report, ASPSP lookup). `scripts/informe_mensual.py` in particular is meant to be run first when asked to
"review my accounts" — it reuses `advisor.engine.get_advice` and `services.dashboard_service` rather than
recomputing things ad hoc; prefer following that same composition when adding new reporting logic.

Templates in `app/templates/` are server-rendered Jinja2 (one file per router/page), sharing
`base.html`; static assets (CSS, a vendored `chart.min.js`) live in `app/static/`, mounted at `/static`.
