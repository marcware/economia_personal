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

Banco Mediolanum is listed by Enable Banking only as a beta connector that answers `server_error`, so
its movements come from an XLS export via [app/importers/mediolanum.py](app/importers/mediolanum.py) and
[scripts/import_mediolanum.py](scripts/import_mediolanum.py) (idempotent — re-importing the same file
doesn't duplicate transactions). [scripts/scrape_mediolanum.py](scripts/scrape_mediolanum.py) is the
semi-automatic way to get that file: Playwright opens the system Chrome with a persistent profile in
`secrets/mediolanum_chrome`, the user logs in (confirmation in the bank's app) and downloads the extract,
and the script saves it to `data/mediolanum/` and imports it. Never store the bank password. If the
Enable Banking connector ever works, the callback links the session to the existing manual Mediolanum
account and `sync_account` skips movements already imported by hand (same day and amount).

Investments (Bit2Me crypto, Trade Republic gold, Quanloop P2P, the ING pension plan, the Mediolanum
PIAS) are kept **independent of the bank movements**: each is an `Inversion` row
([app/models/inversion.py](app/models/inversion.py)) with its own `Aportacion` ledger (money in/out from
outside the platform, from its API or entered by hand) and its value as the latest `ManualAssetEntry`
whose `name` equals `Inversion.nombre` — so `/patrimonio` sums it with no special case and lists only the
remaining (non-investment) declared assets. `/inversiones`
([inversiones_service.py](app/services/inversiones_service.py)) is the overview; each platform gets its
own module page, built one at a time (so far `/inversiones/bit2me`, `/inversiones/trade-republic`,
`/inversiones/pias`, `/inversiones/plan-ing` and `/inversiones/quanloop`; any other shows "módulo pendiente"). Platforms with an API are listed once in
[app/integrations/plataformas.py](app/integrations/plataformas.py), which `/conexiones`, `/inversiones`
and `scripts/sync_accounts.py` iterate; each keeps per-asset snapshots in `Posicion` (filtered by
`inversion_id`; cash is the `"EUR"` row) and its total as a `ManualAssetEntry`. `Inversion.category_id` points to the bank's "Inversión" subcategory for that investment,
used only by [conciliacion_service.py](app/services/conciliacion_service.py), the "Comparado con el banco"
section of `/inversiones` and of each module: bank charges in that category vs the platform's
aportaciones, both summed per day (a PIAS premium arrives split by fund; two card payments can arrive
as one deposit) and paired within `DIAS` and `TOLERANCIA`. The difference on paired ones is money lost
before investing (the PIAS entry charge, ~6.6 %); unpaired platform deposits are matched to an
*uncategorized* charge of the same amount, which a button can file under the investment. That's the
only place the investment pages read `Transaction` — aportado, value and gain always come from the
platform. Returns are shown both as % over aportado and as an annual TIR
(`inversiones_service.tir`, not given under `DIAS_MIN_TIR` days of history).

Bit2Me ([app/integrations/bit2me/](app/integrations/bit2me/), read-only key in `.env` as
`BIT2ME_API_KEY`/`BIT2ME_API_SECRET`): requests are signed `base64(HMAC-SHA512(secret,
SHA256("nonce:path")))`, the same scheme as the official `bit2me-devs/bit2me-mcp`; prices come from the
public `/v3/currency/ticker`. [cartera.py](app/integrations/bit2me/cartera.py) rebuilds the portfolio
from Bit2Me's own history (`/v2/wallet/transaction` + Pro trades from `/v1/trading/trade`, which the
wallet history doesn't show): external deposits/withdrawals (origin/destination class card or
bank-transfer) are the aportaciones; per coin, FIFO cost of what's left, realized result of past sells,
and Earn rewards at zero cost; wallet ↔ Earn ↔ Pro moves are internal. `latente + realizado − comisiones
= valor − aportado` holds exactly (checked against the real account). `sync_service.sincronizar` stores
new aportaciones (deduplicated by Bit2Me operation id), a `CriptoPosicion` snapshot per coin and a
`ManualAssetEntry("Bit2Me")` total; it runs from "Sincronizar ahora" on `/conexiones`,
`scripts/sync_accounts.py`, and on opening `/inversiones` or `/inversiones/bit2me` when the last snapshot
is older than `HORAS_FOTO`.

Trade Republic ([app/integrations/traderepublic/](app/integrations/traderepublic/)) has no public API: it
goes through `pytr` (its private web API), pinned in `pyproject.toml` to a commit audited by hand on
2026-11-11 (PIN only sent to `api.traderepublic.com`, PyPI build identical to the source) — don't bump it
without reviewing the diff. Phone and PIN live in `.env` (`TRADEREPUBLIC_PHONE`/`TRADEREPUBLIC_PIN`, the
user's choice); login is pytr's v2 web login, confirmed with a tap in the phone app from
`/inversiones/trade-republic`, and the session cookies are saved in `secrets/`. All reads go through
`client.Lector`, which only exposes the read calls in `LECTURAS` — pytr can also place orders and pay
out, and nothing here may call those. Cost per position is Trade Republic's own `averageBuyIn`;
aportaciones are deposits/removals classified with pytr's `tr_event_type_mapping`.

The Mediolanum PIAS ([app/integrations/mediolanum/pias.py](app/integrations/mediolanum/pias.py)) has no
API and is read from the online banking (`www.bmedonline.es`, an ASP.NET WebForms **frameset**: all
content lives in the frame named `area`, not the page) inside the session the user opens in
`scripts/scrape_mediolanum.py` — right after login, before the account-extract download (`--solo-pias`
stops there; `/inversiones/pias` has a button that launches it). The landing page's PIAS link carries the
balance in its `aria-label`; firing its `__doPostBack` selects the policy, then `basepage.aspx?a=2401`
is the extract (requested year by year back to the start) and `a=2407` the portfolio. Aportaciones are
the SUSCRIPCION rows (what reaches the funds, already net of entry charges); "Gastos de admón." are
paid in units and kept as a realized loss per fund; "ABONO FIDELIDAD" units come free. It is not in
`plataformas.py`: it needs the user's login, so it never runs on its own.

The ING pension plan ([app/integrations/ing/plan_pensiones.py](app/integrations/ing/plan_pensiones.py))
isn't in the PSD2 data either. `scripts/scrape_ing.py` opens Chrome (profile `secrets/ing_chrome`), the
user logs in, and the SPA's own call to `api.ing.ingdirect.es/position-keeping` is captured (the plan is
the `PENSION` product: balance and `LOCAL_UUID`); then `/genoma_api/rest/products/<id>/movements` is
fetched from inside the page so it rides the user's session. A contribution "pendiente de valoración"
has been charged but has no units yet — it's kept as a pending `"EUR"` position, not as a loss. The
same position-keeping response also has the Cuenta Naranja balance and the mortgage's outstanding
capital (not used yet).

Quanloop ([app/integrations/quanloop/cuenta.py](app/integrations/quanloop/cuenta.py)) has no public API
either. `scripts/scrape_quanloop.py` opens Chrome (profile `secrets/quanloop_chrome`; login is a link by
email + confirmation in its app, and the session doesn't survive a closed browser), waits for the
dashboard's call to `/int/account-statement`, then from inside the page asks for the full statement (JSON:
TOPUP = aportación, withdrawals negative, `INTEREST_PAYOUT`/`CASHBACK_PAYOUT` = the return, paid into
the account and reinvested), the daily-investments report (server-rendered HTML: split per risk plan)
and the dashboard (interest earned but paid on the 15th next month, counted in the value as a
`PENDIENTE` row). Interest collected is stored as `realizado_eur` on the `"EUR"` row.

New sites are mapped first with `scripts/explorar_web.py <sitio>`, which records
what the site receives (never what's sent) into `secrets/<sitio>_exploracion/`.

## Architecture

Layout is a standard layered FastAPI app under `app/`:

- **models/** — SQLAlchemy ORM models (`Base` from [app/database.py](app/database.py)). `app/models/__init__.py`
  re-exports everything and is imported by `migrations/env.py` so autogenerate picks up all tables —
  add new models there too.
- **routers/** — one `APIRouter` per feature area (dashboard, transactions, budgets, categories,
  connections, advice, notes, net_worth, inversiones, transfer_candidates, anual), each mounted in [app/main.py](app/main.py).
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
  services (dashboard, advisor 50/30/20, anual) still count only negatives. The dashboard counts the
  salary (`disponible_service._categoria_nomina`) paid on or after `DIA_NOMINA_ADELANTADA` as income of
  the month it funds, not the one it lands in, so the open month isn't thousands in the red until the
  27th; its spend stays per calendar month, like the budgets. Income, everywhere, is only
  a positive movement in an INGRESO-group category (a loan paid into the account or a refund is not
  income; a loan disbursement goes to the EXCLUIDO "Abono de financiación", never to the loan-repayment
  category, where it would net against the instalments as a refund); `budget_service.ingresos_base` is the shared "income to measure the month against" (expected
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
  inversión pendiente − cuota de las huchas que falta por pasar − lo que falta para arrancarlas`. The
  payday is auto-detected (largest INGRESO category); a pay
  cycle maps to the budget month it ends in (27 sep → 26 oct = octubre), using that month's budgets or,
  if it has none, the median of the previous 3 months. For variable NECESIDAD categories it reserves the
  larger of budget and that median (a too-low grocery ceiling must not inflate "libre"). It reuses
  `budget_service` for the investment commitment and `huchas_service` for the set-asides rather than
  recomputing them. The pay cycle's own month is not in the annual set-aside (it starts the month after,
  via `hucha_anual(tras=…)`): that month's `anual` payments are
  reserved as pending fixed costs instead — budget if any, else `anual_service.pagos_anuales_mes` —
  or, right after payday, they'd be counted twice.
  [huchas_service.py](app/services/huchas_service.py) holds the two "huchas", money set aside every
  month for what doesn't fit a normal month and kept outside the day-to-day accounts, in ING's Cuenta
  Naranja (a savings account the PSD2 connection doesn't expose: `scripts/scrape_ing.py` reads its
  balance from the same position-keeping response and stores it as the `ManualAssetEntry` "Cuenta
  Naranja"). *Recibos anuales* is computed (`anual_service.hucha_anual`: the excess over a normal month
  of each `anual` category in the next 12 months; with the hucha already topped up, its monthly average
  suffices — `inicial` is what must be there today for that to arrive in time). *Viajes e imprevistos*
  has a quota the user chooses (`UserSettings.hucha_variable`); the suggestion comes from history:
  `anual_service.hucha_grandes` (months where a variable DESEO category ran ≥ `UMBRAL_PICO` over its
  median) plus `hucha_imprevistos` (lumpy NECESIDAD categories, median ≤ `MEDIANA_MAX_IMPREVISTO`,
  ≥ `UMBRAL_IMPREVISTO` over it — house, garage, appliances), with no category flag behind either.
  What has already gone to the Cuenta Naranja this cycle is `traspasado`: outgoing "TRASPASO…"
  transfers without a matching incoming one in another account the app knows (ING's round-ups
  included). On `/presupuestos`, a variable category's overspend that meets those same thresholds is
  shown as paid by the hucha, not as "te has pasado".
  [dinero_service.py](app/services/dinero_service.py) powers "Mi dinero" (`/dinero`): every account has
  a job (`Account.rol`: NOMINA = Mediolanum, salary and emergency fund; RECIBOS; DIA; AHORRO = unassigned)
  plus the Cuenta Naranja for the huchas. Each gets what it should hold (rest of the cycle's variable
  budget, pending fixed costs and investment, 6 months of the budget's NECESIDAD plus annual bills, the
  huchas' `inicial`) and the page lists the transfers that put everything in place, from AHORRO first.
  Once accounts have roles, the home's "libre" only looks at DIA + RECIBOS. Mediolanum's balance is the
  last imported extract's (`scripts/import_mediolanum.py` stores it as a declared asset).
  [pendientes_service.py](app/services/pendientes_service.py) builds the short "Pendiente" strip on the
  home page (budgets exceeded, hitos at risk, recent uncategorized movements, bank consent about to
  expire); it only counts and links, the arithmetic stays in `budget_service`/`goal_service`.
  [hormiga_service.py](app/services/hormiga_service.py) measures "gastos hormiga" (≤20 € charges in
  non-recurrent DESEO categories or uncategorized) shown on the dashboard;
  [libertad_service.py](app/services/libertad_service.py) is the financial-independence panel on
  `/patrimonio` (emergency fund in months of NECESIDAD spend, consumer debt, savings rate, gasto anual ×
  25 target and projections at a 4 % real return). Its figures look ahead: when there's a budget
  (`mes_del_plan`: the month after the pay cycle's if already prepared, else the cycle's) they come
  from `plan_mensual` — expected regular income, budgeted spend plus the huchas' quota, committed
  investment, NECESIDAD limits plus the annual-bills quota — and the last 6 closed months are shown
  beside it as `real`, so a paid-off loan or a holiday doesn't keep saying "you spend more than you
  earn" for half a year (the advisor's deficit check follows the same split). `/dinero`'s emergency-fund
  target is this same `objetivo_colchon`. The emergency fund counts `ManualAssetEntry` rows flagged
  `liquido` plus the balance of AHORRO-role accounts; the Cuenta Naranja is not counted as invested;
  consumer debt is every declared liability whose name doesn't contain "hipoteca".
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
  monthly; see `budget_service.gastos_anuales`). Each yearly bill wants its own `anual` category so `/anual` and the
  hucha see it: SUMA charges IBI and car tax with the same description, so they are split by amount rules
  (`CategorizationRule.min_abs_amount`, larger first) into IBI Palacete / IBI cochera / Impuesto del coche. `AHORRO`-group categories are never budgeted as a
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
`scripts/sync_accounts.py`; automatic changes are flagged in `Budget.ajuste_auto` and can be undone. On the page, variable categories are split into "te has pasado" and "van bien" (sorted by
spend, untouched ones last), because the net `limite − gasto` hides overspend behind unspent
ceilings; each row shows `gasto_habitual` (median of the last 6 closed months, robust to a holiday
month) and, when that is ≥ `FACTOR_POCO_REALISTA` × the limit, offers to raise the limit to it. The month's budget total is a
sum of ceilings, not "what you can spend": `budget_service.balance_mes` puts it next to expected income
(median of the last 3 closed months of each *regular* INGRESO category — present every month with a
stable amount, so nómina/alquiler count and Bizum refunds don't) and splits the margin into investment,
the huchas and what's left to save (which can stay in Mediolanum; `traspaso_necesario` is what the plan
needs moved from there to ING). An income that has ended (the rent of a sold flat) is cut with
`Category.fin_ingreso`, or the 3-month median would keep counting it. `FinancialGoal`
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

UI conventions: every colour comes from the CSS variables at the top of
[app/static/css/style.css](app/static/css/style.css), which define a light and a dark theme (follows
the system setting) — don't hardcode hex colours or inline `style="background:…"` in templates; use
the classes (`button-secondary`, `positive`/`negative`, `advice-*`, `tag`, `badge`). A top-level
`<section>` renders as a card. Amounts go through the `eur` Jinja filter (`{{ x|eur }}` → `1.234,56 €`,
`|eur(0)` without decimals; defined in [app/templating.py](app/templating.py)) and numeric table cells
take the `num` class (right-aligned, tabular figures). Charts load
[app/static/js/charts.js](app/static/js/charts.js) after `chart.min.js`: it themes Chart.js from the
same CSS variables and exposes `tema` (colours, `tema.eur`). Amounts inside Python-built texts (advice,
pendientes) use `app.formato.eur`/`numero`, the same functions behind the filters.
[app/static/js/app.js](app/static/js/app.js) is loaded on every page and is progressive enhancement
only: after any POST form it restores the scroll position and shows a toast (`data-aviso="…"` on the
form sets its text, `data-enviando="…"` the button text while it runs); `form[data-autoenviar]` submits
on select change; `.solo-si-cambia` hides the save button until the value changes;
`<input data-filtra=".selector">` filters blocks client-side. Long pages keep the actionable part
visible and fold the rest: `<section class="plegable"><details><summary><h2>…</h2><span
class="resumen">key figure</span></summary>…` — put the figure that answers the section's question in
the summary so it rarely needs opening. Static files are cache-busted with `?v={{ version_estaticos() }}`. The self-signed cert blocks browser
automation on :8000; to look at pages from a tool, run a second plain-HTTP `uvicorn app.main:app --port 8001`.
