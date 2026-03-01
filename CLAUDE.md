# CLAUDE.md

## Project Purpose

Investment Analyzer is a personal AI-powered stock research and paper-trading
system with two main workflows:

- Weekly research:
  - screen a 70-stock watchlist
  - generate thesis snapshots with Claude
  - self-correct prior theses the following week

- Daily paper trading:
  - run a smaller daily screen
  - research non-held candidates
  - let Claude make constrained buy/sell decisions for a 1,000-point paper portfolio

The system is designed around explainable reasoning, stored outputs, and
auditable trade/correction history.

## Business Context

Business and product-planning context lives in `business_case/`.

Read these files when the task involves product direction, prioritization, feature planning, user needs, or business rationale:

- `business_case/PRD.md`
- `business_case/business_case.md`
- `business_case/user_research.md`

Use `CLAUDE.md` for repo operating rules and architecture boundaries.
Use `business_case/` for product and business context.

## Current Architecture

- `agent/`
  - LLM-driven or judgment-driven modules.
  - Current modules:
    - `researcher.py`
    - `self_corrector.py`
    - `portfolio_manager.py`

- `logic/`
  - Deterministic domain logic.
  - Current modules:
    - `screener.py`
    - `evaluations/`

- `logic/evaluations/`
  - Deterministic quality checks for LLM agent outputs.
  - Current modules:
    - `researcher_eval.py`
    - `self_corrector_eval.py`
    - `portfolio_manager_eval.py`

- `tools/`
  - External integrations and low-level fetchers.
  - Current modules:
    - `finnhub_client.py`
    - `edgar_client.py`
    - `news_client.py`
    - `reddit_client.py`
    - `sec_xbrl_client.py`

- `workflows/`
  - Thin orchestration entrypoints.
  - Current modules:
    - `run_daily.py`
    - `run_weekly.py`
    - `dashboard/server.py`

- `memory/`
  - Persistence and stored state.
  - Current files:
    - `database.py`
    - `watchlist.json`
    - `investment_analyzer.db`

- `prompts/`
  - Prompt templates used by LLM-driven agents.

- `business_case/`
  - Product, business, and user-context documents.

- `.project/`
  - Technical project documentation, metadata, and reusable templates.

## Architectural Rules

- Keep LLM calls in `agent/`.
- Keep deterministic scoring, ranking, validation, and hard rules in `logic/`.
- Put deterministic LLM output evaluators and retry-policy rules in `logic/evaluations/`.
- Name evaluator modules with the `_eval.py` suffix to distinguish them from the agent modules they judge.
- Keep provider-specific API code in `tools/`.
- Keep workflows thin. A workflow should coordinate steps, not hold business logic.
- Keep database and persistent state concerns in `memory/`.
- Keep product/business context in `business_case/`.
- If a module mixes orchestration, LLM reasoning, and deterministic logic, split it.

## Project-Specific Working Rules

- Do not put new data-provider logic inside `agent/`.
- Do not put screener math or portfolio constraints inside `workflows/`.
- Prefer extending `logic/screener.py` for new deterministic ranking factors.
- Prefer placing output-quality checks, rerun criteria, and fallback acceptance rules in `logic/evaluations/`.
- Prefer extending `tools/sec_xbrl_client.py` or other `tools/*_client.py` files for new free data sources.
- Use prompt files in `prompts/` instead of hardcoding long prompt strings in Python.
- Persist new run outputs through `memory/database.py`, not ad hoc JSON files.
- Put PRDs, business-case docs, user research, and market/context notes in `business_case/`.

## Key Runtime Behavior

- Daily workflow default:
  - `workflows.run_daily` currently limits the watchlist to 5 stocks by default.
  - Override with `--watchlist-limit N`.

- Weekly workflow:
  - screens the full active watchlist unless `--ticker` is provided.
  - runs a learning pass after corrections are logged.

- Learning loop:
  - uses recent correction history to generate sector caution state and persistent prompt hints
  - applies recency-weighted decay instead of treating all historical errors equally
  - current default: 12-week max lookback with weekly decay factor `0.85`

- Portfolio rules:
  - starting budget: `1000` points
  - long-only
  - min position size: `40`
  - max position size: `200`
  - max open positions: `20`

- Dashboard:
  - served by FastAPI from `workflows/dashboard/server.py`
  - reads snapshots, corrections, portfolio, and transaction history from SQLite

## Commands

Setup and local run:

```bash
pip install -r requirements.txt
python3 -m memory.database
python3 -m workflows.run_daily --force
python3 -m workflows.run_weekly
python3 -m workflows.dashboard.server
```

Useful variants:

```bash
python3 -m workflows.run_daily --dry-run
python3 -m workflows.run_daily --force --watchlist-limit 5
python3 -m workflows.run_weekly --dry-run
python3 -m workflows.run_weekly --ticker AAPL MSFT
```

## Environment

Expected environment variables:

```bash
ANTHROPIC_API_KEY=...
FINNHUB_API_KEY=...
DB_PATH=memory/investment_analyzer.db
SCHEDULER_TZ=Asia/Kolkata
SEC_USER_AGENT="Investment Analyzer research@example.com"
```

Notes:

- The app depends on external network access for Finnhub, SEC EDGAR/XBRL, news, and market data.
- If network access is unavailable, the workflows may degrade to empty or fallback data and some research steps may stall or fail.
- Railway startup is handled by `start.sh`.

## Coding Conventions

- Keep code ASCII unless a file already uses Unicode deliberately.
- Prefer small, composable helpers over large mixed-responsibility functions.
- Prefer explicit imports from package modules.
- Keep provider adapters narrow and defensive:
  - catch upstream API errors
  - return empty dict/list or `None` when appropriate
  - avoid crashing workflows on a single provider failure
- Keep scoring tolerant of missing values.
- Enforce portfolio constraints in code, not just in prompts.
- When changing prompts, keep output schemas stable unless the parsing code is updated in the same change.

## Security And Risk Rules

- Never hardcode API keys, secrets, or tokens in source files, prompts, tests, or docs.
- Read credentials from environment variables only.
- Store local secrets in `.env` or another ignored local file, not in tracked repo files.
- Treat `.env`, local SQLite files, and provider credentials as sensitive and do not commit them.
- Do not log secrets, raw auth headers, or full provider request URLs when they include tokens.
- Sanitize error handling so upstream provider failures do not leak credentials into logs.
- Prefer least-privilege environment configuration in deployment platforms.

- This project is a research and paper-trading system, not a live brokerage executor.
- Do not add real-money trading integrations unless the project requirements are explicitly changed.
- Keep portfolio rules enforced in deterministic code even if the LLM suggests violating them.
- Do not allow prompt-only controls for position sizing, max positions, or cash constraints.
- Treat external market/news/provider data as unreliable input:
  - handle missing values
  - handle stale values
  - handle malformed responses
  - fail safely

- Do not present outputs as financial advice.
- Preserve auditability:
  - store reasoning for trades and thesis changes
  - keep correction logs intact
  - avoid silent mutation of historical records

- When adding new providers or workflows, consider:
  - rate limits
  - data licensing/display restrictions
  - failure modes during network outages
  - whether the workflow degrades safely when the provider is unavailable

- In deployed environments:
  - use persistent storage for the SQLite database
  - keep `DB_PATH` outside ephemeral directories
  - avoid destructive startup behavior that can replay trades or overwrite state

## Data and Persistence Conventions

- SQLite is the source of truth for:
  - stock snapshots
  - correction logs
  - portfolio positions
  - transactions
  - portfolio snapshots

- Watchlist seed data lives in:
  - `memory/watchlist.json`

- Database helpers live in:
  - `memory/database.py`

- Avoid creating new persistent stores unless there is a clear reason not to use SQLite.

## Where New Code Should Go

- New LLM-based thesis/review/decision module:
  - `agent/`

- New deterministic screener factor, ranking function, or rule validator:
  - `logic/`

- New deterministic LLM output evaluator:
  - `logic/evaluations/`

- If an agent module is named `x.py`, prefer naming its deterministic evaluator `x_eval.py`.

- New deterministic policy that decides whether to accept, retry, fallback, or fail an agent output:
  - `logic/evaluations/`

- New market-data or SEC/news client:
  - `tools/`

- New scheduled process, run entrypoint, or orchestration layer:
  - `workflows/`

- New schema, cache, or persistence helper:
  - `memory/`

- New prompt template:
  - `prompts/`

## Validation Expectations

- At minimum, run a compile check after structural changes:

```bash
python3 -m py_compile agent/*.py logic/*.py tools/*.py memory/*.py workflows/*.py workflows/dashboard/*.py
```

- Prefer dry-run workflow validation before changing full live behavior:

```bash
python3 -m workflows.run_daily --dry-run
python3 -m workflows.run_weekly --dry-run
```

- For import/path refactors, verify:
  - `python3 -m workflows.run_daily`
  - `python3 -m workflows.run_weekly`
  - `python3 -m workflows.dashboard.server`

## Things To Avoid

- Do not treat `workflows/` as a dumping ground for business logic.
- Do not put API response-shaping logic directly in prompt assembly when it can live in `tools/`.
- Do not couple deterministic validation tightly to LLM output formatting.
- Do not introduce another persistence layer casually.
- Do not move portfolio rule enforcement into prompts alone.

## Deployment Notes

- The project is deployed on Railway.
- `start.sh` initializes the DB, optionally runs an initial daily workflow, starts the scheduler, and launches the dashboard server.
- In deployed environments, `DB_PATH` should point at a persistent volume path.
