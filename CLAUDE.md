# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local personal-finance app (Spanish UI/comments) the user runs against his own real bank data. It
pulls bank movements from ING (and manually from Banco Mediolanum, and soon Bit2Me/Quanloop) via the
[Enable Banking](https://enablebanking.com) Open Banking/PSD2 API — no manual CSV exports for ING — then
provides a monthly income/expense dashboard by category, a rule-based "financial coach" advice engine,
per-month budgets with a fixed/variable/annual split, monthly financial goals ("hitos"), and a net-worth
tracker. Server-rendered with FastAPI + Jinja2 (no frontend framework/build step).

Core features are built and in daily use; there is no automated test suite (see below) — everything is
verified by hand against the user's real data (`scripts/informe_mensual.py` is the standard way to do
that). Don't rely on a phase-plan file under `~/.claude/plans/` for "current status" — those are
per-session scratch plans and go stale; this file and `git log` are the durable record. When picking up
new work, write its plan there as usual, but fold anything durable (new architecture, new conventions)
back into this file once built, the way the sections below describe budgets/goals/categorization.

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
doesn't duplicate transactions). Low volume (a handful of movements), so this stays manual rather than
built out further.

Bit2Me (crypto) and Quanloop (P2P lending) aren't transactional accounts in this app at all — they're
tracked as net-worth snapshots via `/patrimonio`'s "Inversiones declaradas" form
(`ManualAssetEntry`, [app/services/net_worth_service.py](app/services/net_worth_service.py)): the user
reports a value periodically (by hand, or by pasting a report he sends) and it's stored as one more
row — the table is append-only, so full history survives even though the net-worth summary shows only
the latest per name. Bit2Me has a public API; if the user ever provides credentials, a live balance sync
is a reasonable follow-up, but don't build against it speculatively without real credentials to test
against.

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
  [budget_service.py](app/services/budget_service.py) is the single source of the
  gasto-real-vs-límite arithmetic (router, advisor and `informe_mensual.py` all call it — don't
  recompute it locally); [goal_service.py](app/services/goal_service.py) is the equivalent for
  monthly financial goals ("hitos").
  [disponible_service.py](app/services/disponible_service.py) powers the "Hoy" home page (`/`): what's
  free to spend *until the next payday*, not per calendar month — the salary lands ~27th and funds the
  following month, and the big fixed charges (mortgage 1st, loans 3rd, utilities ~10th) fall after it.
  `libre = saldo de cuentas API (sin Mediolanum) − fijos pendientes − necesidades variables pendientes −
  inversión pendiente − apartado anual`. The payday is auto-detected (largest INGRESO category); a pay
  cycle maps to the budget month it ends in (27 sep → 26 oct = octubre), using that month's budgets or,
  if it has none, the median of the previous 3 months. It reuses `budget_service` for the investment
  commitment and annual expenses rather than recomputing them.
  [hormiga_service.py](app/services/hormiga_service.py) measures "gastos hormiga" (≤20 € charges in
  non-recurrent DESEO categories or uncategorized) shown on the dashboard;
  [libertad_service.py](app/services/libertad_service.py) is the financial-independence panel on
  `/patrimonio` (emergency fund in months of NECESIDAD spend, consumer debt, savings rate, gasto anual ×
  25 target and projections at a 4 % real return). The emergency fund counts only `ManualAssetEntry`
  rows flagged `liquido`; consumer debt is every declared liability whose name doesn't contain
  "hipoteca".
- **categorization/** — rule-based auto-categorization. [engine.py](app/categorization/engine.py)
  applies the highest-priority active `CategorizationRule` whose (normalized) description pattern
  matches and whose amount sign matches; [normalize.py](app/categorization/normalize.py) normalizes
  descriptions before matching; [seed_rules.py](app/categorization/seed_rules.py) defines the initial
  category tree and seed rules (loaded by [scripts/seed_categories.py](scripts/seed_categories.py)).
  Each leaf `Category` carries three independent tags, don't conflate them: `budget_group`
  (NECESIDAD/DESEO/AHORRO/INGRESO/EXCLUIDO, drives the 50/30/20 rule), `recurrente` (same amount every
  month, a commitment already made — e.g. the gym is DESEO but recurrente) and `anual` (only meaningful
  when `recurrente=True`: lands in one or two lump payments a year — insurance, IBI — rather than spread
  monthly; see `budget_service.gastos_anuales`). `AHORRO`-group categories are never budgeted as a
  ceiling (see `Budget` below) — track a savings/investment floor as a `GoalType.INVERSION_MIN` hito
  instead.
- **advisor/** — the "financial coach" advice engine. [engine.py](app/advisor/engine.py)'s `get_advice()`
  is the entrypoint: loads the month's transactions as a pandas DataFrame
  ([data.py](app/advisor/data.py)), then runs independent checks (`rule_50_30_20`, `budget_alerts`,
  `goal_alerts`, `anomaly_and_savings`, `habitos`), merging and sorting results by severity (`SEVERITY_ORDER` in
  [types.py](app/advisor/types.py)). New advice checks should follow this same pattern: a pure function
  taking the DataFrame/db + settings and returning a list of `Advice`. `anomaly_and_savings.check_anomalies`
  skips `AHORRO`-group categories on purpose — spending more on savings/investment is good, not anomalous.
- **integrations/enablebanking/** — the Enable Banking API client and OAuth-style consent/session flow.
  `EnableBankingClient` ([client.py](app/integrations/enablebanking/client.py)) handles JWT auth and raw
  HTTP; `auth_flow.py` and `sync_service.py` build on top of it.
- **importers/** — one-off/manual file-based importers (currently Mediolanum XLS) for banks not
  reachable via Enable Banking.

`Budget` ([app/models/budget.py](app/models/budget.py)) is keyed on `(category_id, year, month)`, not a
permanent per-category limit — it's meant to be prepared ahead of time for a future month (see
`budget_service.selectable_months`, which is why `/presupuestos` can navigate to months with no
transactions yet) and copied forward month to month. `FinancialGoal`
([app/models/goal.py](app/models/goal.py)) is the analogous per-month row for hitos, a closed
`GoalType` enum rather than a rules DSL — extend the enum + `goal_service._actual`/`_estado` dispatch for
a new kind of goal, don't add a generic expression language.

`scripts/` holds standalone maintenance/reporting scripts run directly with `python scripts/<name>.py`
against a real `SessionLocal()` (seeding categories, bulk/re-categorization, account sync, monthly
report, ASPSP lookup, seeding a month's budgets). `scripts/informe_mensual.py` in particular is meant to
be run first when asked to "review my accounts" — it reuses `advisor.engine.get_advice`,
`services.dashboard_service` and `services.budget_service`/`goal_service` rather than recomputing things
ad hoc; prefer following that same composition when adding new reporting logic.
`scripts/seed_presupuestos.py` loads a hand-maintained annual template (frozen from the user's old
spreadsheet, not read live from it) into a given month's budgets — see its docstring before changing the
template values.

Templates in `app/templates/` are server-rendered Jinja2 (one file per router/page), sharing
`base.html`; static assets (CSS, a vendored `chart.min.js`) live in `app/static/`, mounted at `/static`.
