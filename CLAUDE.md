# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local personal-finance app (Spanish UI/comments) the user runs against his own real bank data. It
pulls bank movements from ING (and manually from Banco Mediolanum, and soon Bit2Me/Quanloop) via the
[Enable Banking](https://enablebanking.com) Open Banking/PSD2 API — no manual CSV exports for ING — then
provides a monthly income/expense dashboard by category, a rule-based "financial coach" advice engine,
per-month budgets with a fixed/variable/annual split, monthly financial goals ("hitos"), and a net-worth
tracker. Server-rendered with FastAPI + Jinja2 (no frontend framework/build step).

Core features are built and in daily use; the automated tests are few (see below) — most things are
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

Tests (`make test` / `pytest`) cover only the money arithmetic so far
([tests/test_services/test_dinero.py](tests/test_services/test_dinero.py)): net spend, what counts as
income, the pay cycle, the home page's "libre" and `copy_month`. They run on an in-memory SQLite built
by [tests/conftest.py](tests/conftest.py) and never touch `data/economia.db`. No lint/format tooling is
configured in `pyproject.toml`.

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
sync in [app/integrations/enablebanking/sync_service.py](app/integrations/enablebanking/sync_service.py)
(`sync_all`, shared by `scripts/sync_accounts.py` and the "Sincronizar ahora" button on `/conexiones`).

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
  connections, advice, notes, net_worth, transfer_candidates, anual), each mounted in [app/main.py](app/main.py).
  Routers call into `services/`/`advisor/`/`categorization/` and render Jinja2 templates from
  `app/templates/` via the shared `templates` instance in [app/templating.py](app/templating.py)
  (which also injects template globals, e.g. the pending-transfer-candidates nav badge).
- **services/** — cross-cutting business logic used by routers and scripts (dashboard aggregation,
  net worth, transfer-candidate detection between own accounts).
  [budget_service.py](app/services/budget_service.py) is the single source of the
  gasto-real-vs-límite arithmetic (router, advisor and `informe_mensual.py` all call it — don't
  recompute it locally). Spend there is *net of refunds*: a positive movement categorized in a
  NECESIDAD/DESEO category (a Bizum paying back a share, a shop refund) subtracts from that category's
  spend and can leave it negative when the refund lands in a different month than the charge; other
  services (dashboard, advisor 50/30/20, anual) still count only negatives. Income, everywhere, is only
  a positive movement in an INGRESO-group category (a loan paid into the account or a refund is not
  income); `budget_service.ingresos_base` is the shared "income to measure the month against" (expected
  income while the month is open) used by hitos, the 50/30/20 rule and the dashboard.
  "Dinero de paso" (paid on someone's behalf and paid back: botes, the tenant's bills) is excluded from
  both spend and income; `budget_service.dinero_de_paso` only lists it on `/presupuestos` with the
  month's outstanding balance, and finds the category by its seed name (`CATEGORIA_DINERO_DE_PASO`).
  [goal_service.py](app/services/goal_service.py) is the equivalent for
  monthly financial goals ("hitos").
  [disponible_service.py](app/services/disponible_service.py) powers the "Hoy" home page (`/`): what's
  free to spend *until the next payday*, not per calendar month — the salary lands ~27th and funds the
  following month, and the big fixed charges (mortgage 1st, loans 3rd, utilities ~10th) fall after it.
  `libre = saldo de cuentas API (sin Mediolanum) − fijos pendientes − necesidades variables pendientes −
  inversión pendiente − apartado anual`. The payday is auto-detected (largest INGRESO category); a pay
  cycle maps to the budget month it ends in (27 sep → 26 oct = octubre), using that month's budgets or,
  if it has none, the median of the previous 3 months. For variable NECESIDAD categories it reserves the
  larger of budget and that median (a too-low grocery ceiling must not inflate "libre"). It reuses
  `budget_service` for the investment commitment and `anual_service.hucha_anual` for the annual set-aside
  (the same figure `/anual` shows) rather than recomputing them. It also subtracts
  `anual_service.hucha_grandes`: the monthly set-aside for big non-monthly discretionary spend
  (holidays, electronics), derived from history — months where a variable DESEO category ran
  ≥ `UMBRAL_PICO` over its 12-month median — with no category flag behind it.
  [pendientes_service.py](app/services/pendientes_service.py) builds the short "Pendiente" strip on the
  home page (budgets exceeded, hitos at risk, recent uncategorized movements, bank consent about to
  expire); it only counts and links, the arithmetic stays in `budget_service`/`goal_service`.
  [hormiga_service.py](app/services/hormiga_service.py) measures "gastos hormiga" (≤20 € charges in
  non-recurrent DESEO categories or uncategorized) shown on the dashboard;
  [libertad_service.py](app/services/libertad_service.py) is the financial-independence panel on
  `/patrimonio` (emergency fund in months of NECESIDAD spend, consumer debt, savings rate, gasto anual ×
  25 target and projections at a 4 % real return). The emergency fund counts only `ManualAssetEntry`
  rows flagged `liquido`; consumer debt is every declared liability whose name doesn't contain
  "hipoteca".
  [anual_service.py](app/services/anual_service.py) powers `/anual`, the live version of the user's
  old annual spreadsheet (`data/2026_Gastos.xlsx`): category × month grid where closed months are real
  spend and the current/future months are a forecast (budget if any; for `anual` categories the same
  month last year, never below the budget — flagged ⚠ when the budget is shorter; otherwise median of 3 /
  trimmed mean of 6 closed months). Its `hucha_anual` gives the constant monthly set-aside that covers the
  next 12 months of `anual` lump payments (only the excess over a normal month).
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
transactions yet) and copied forward month to month. Open months (current and future, only if they
already have budgets) also adapt on their own: `budget_service.ajustar_mes` adds a category with spend in
≥2 of the last 6 months (limit = monthly mean, rounded up to 5 €) and removes one with no spend in 6
months — altas/bajas only, never recalculating existing limits, and never touching anything the user set,
edited or removed by hand (`Budget.fijado`, which `copy_month` carries over, including hand-removed
rows). It runs on opening `/presupuestos` and `/` and after
`scripts/sync_accounts.py`; automatic changes are flagged in `Budget.ajuste_auto` and can be undone. The month's budget total is a
sum of ceilings, not "what you can spend": `budget_service.balance_mes` puts it next to expected income
(median of the last 3 closed months of each *regular* INGRESO category — present every month with a
stable amount, so nómina/alquiler count and Bizum refunds don't) and splits the margin into investment,
what stays in Mediolanum after the transfer to ING (the colchón — savings, not spend) and unassigned. `FinancialGoal`
([app/models/goal.py](app/models/goal.py)) is the analogous per-month row for hitos, a closed
`GoalType` enum rather than a rules DSL — extend the enum + `goal_service._actual`/`_estado` dispatch for
a new kind of goal, don't add a generic expression language. Income-based hitos (`AHORRO_MIN`,
`TASA_AHORRO_MIN`) measure the open month against `budget_service.ingresos_previstos`, not real income
— the salary lands ~27th, so until then real income is near zero and the rate would be absurd.

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
