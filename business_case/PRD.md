# Product Requirements Document
# Investment Analyzer — AI-Powered Stock Research & Paper Trading Agent

**Date:** 2026-02-28
**Status:** Live (V1 + V2 deployed)
**Author:** Sailendra Kumar

---

## 1. Overview

### Vision
A personal AI-powered investment system with two modes:
- **V1 (Weekly):** A self-correcting S&P 500 research agent that observes, reasons, and audits its own prior reasoning week-over-week — building a verifiable track record.
- **V2 (Daily):** A live paper trading agent that manages a 1,000-point portfolio, making real buy/sell decisions every weekday at noon using Claude Sonnet.

### Why Build This
Most stock screeners give you a number. None of them show you the reasoning behind it, whether that reasoning held up, or how it evolved. V1 fills that gap. V2 goes further — putting the agent's judgment to the test in a real (paper) portfolio with real constraints and consequences.

---

## 2. Mode Comparison

| | V1 — Weekly Research | V2 — Daily Paper Trading |
|--|---------------------|--------------------------|
| **Cadence** | Weekly (Mondays 06:00) | Daily weekdays (12:00 noon IST) |
| **LLM role** | Generate + correct thesis | Make buy/sell decisions |
| **Output** | Research snapshots + corrections | Trades + equity curve |
| **Budget** | N/A | 1,000 pts starting (1 pt = $1) |
| **Run command** | `python -m workflows.run_weekly` | `python -m workflows.run_daily --force` |

---

## 3. Architecture

### V1 — Weekly Research Pipeline
```
Watchlist (70 stocks)
        │
        ▼
┌──────────────┐     ┌────────────────┐     ┌──────────────────┐
│   Screener   │────▶│   Researcher   │────▶│  Self-Corrector  │
│  (all 70,    │     │  (top 20-30,   │     │  (Claude Haiku,  │
│   no LLM)   │     │  Claude Sonnet)│     │   prior week diff)│
└──────────────┘     └────────────────┘     └──────────────────┘
        │                    │                       │
        └────────────────────┴───────────────────────┘
                             │
                             ▼
                       SQLite Database
                             │
                             ▼
                    FastAPI Dashboard
```

### V2 — Daily Paper Trading Pipeline
```
Watchlist (70 stocks)
        │
        ▼
┌──────────────┐     ┌────────────────┐     ┌──────────────────────┐
│   Screener   │────▶│   Researcher   │────▶│  Portfolio Manager   │
│  (top 20     │     │  (non-held     │     │  (Claude Sonnet,     │
│   candidates)│     │   stocks only) │     │   buy/sell decisions)│
└──────────────┘     └────────────────┘     └──────────────────────┘
                                                       │
                                              Execute trades in DB
                                                       │
                                             Portfolio + Transactions
                                                  + Snapshots
                                                       │
                                             FastAPI Dashboard
```

---

## 4. Paper Trading Rules (V2)

| Rule | Value |
|------|-------|
| Starting budget | 1,000 pts (1 pt = $1 USD) |
| Position range | 40–200 pts per position |
| Max positions | 20 open at once |
| Min positions | 10 (after initial deployment) |
| Direction | Long only |
| Shares | Fractional: `shares = pts_invested / buy_price` |
| Stop-loss guidance | Sell if >15% drawdown |
| Cash tracking | `cash = 1000 − Σbuys + Σsell_proceeds` (computed from transactions) |
| Decision maker | Claude Sonnet 4.6 |
| Constraint enforcement | `_validate_decisions()` in `portfolio_manager.py` |

---

## 5. Data Sources

| Source | Purpose | Rate Limit | Library |
|--------|----------|-----------|---------|
| **Finnhub** (free tier) | Fundamentals: P/E, P/B, EV/EBITDA, FCF yield, ROE, debt/equity, news | 60 calls/min | `finnhub-python` |
| **SEC EDGAR** | 10-Q MDA sections, 8-K material events | 10 req/sec | `edgartools` |
| **Google News RSS** | Recent headlines per stock | Unlimited | `feedparser` |
| **Reddit PRAW** | Sentiment from r/investing, r/stocks | 60 req/min | `praw` (optional) |
| **yfinance** | Live prices for portfolio valuation + 1-year price history for charts | Unofficial | `yfinance` |

---

## 6. Database Schema (5 tables)

### `watchlist`
70 curated S&P 500 stocks across 11 GICS sectors. `active` flag for pausing.

### `stock_snapshots` (PK: run_date + ticker)
Weekly research output — thesis, conviction (1–10), valuation signal (Cheap/Fair/Expensive), fundamentals snapshot, key risk, catalyst, second-order effects.
`run_date` format: `YYYY-WW` (ISO year + week number).

### `correction_log`
Weekly self-correction entries. Drift signal: `Stable / Updated / Contradicted`. Error types: `Exogenous Shock / Timing Error / Thesis Error / Data Gap`.

### `portfolio` (PK: ticker)
Open positions. Stores buy price, shares (fractional), current price/value, unrealized P&L.

### `transactions`
Full trade ledger — every BUY and SELL with price, shares, points, reasoning, P&L. Cash balance is always computed from this table, never stored directly.

### `portfolio_snapshots` (PK: date)
Daily equity curve — total value, cash, invested, daily P&L, position count.

---

## 7. Tech Stack

| Component | Technology | Decision |
|-----------|-----------|----------|
| Language | Python 3.11+ | Best finance/data ecosystem |
| Dashboard | FastAPI + vanilla HTML/JS | Switched from Streamlit → NiceGUI → FastAPI. Root cause: both Streamlit and NiceGUI had persistent row-click navigation bugs that couldn't be reliably fixed. FastAPI + native `onclick` resolved this permanently. |
| Charts | Plotly.js (CDN) | Client-side rendering, no server overhead |
| Styling | Tailwind CSS (CDN) | No build step needed |
| Database | SQLite | Zero setup, persistent via Railway volume |
| LLM (thesis + trades) | Claude Sonnet 4.6 | Best reasoning for financial decisions |
| LLM (corrections) | Claude Haiku 4.5 | Cost-efficient for high-volume correction step |
| Scheduler | APScheduler | Python-native cron, timezone-aware via `SCHEDULER_TZ` env var |
| Deployment | Railway | Persistent volume for SQLite, GitHub auto-deploy |

---

## 8. Dashboard Pages

| Page | URL | Description |
|------|-----|-------------|
| Summary | `/` | Sortable stock table, row click → stock detail |
| Portfolio | `/portfolio` | Equity curve, KPI strip, positions table, transaction log |
| Corrections | `/corrections` | Self-correction log with BUY/SELL badges |
| Accuracy | `/accuracy` | Drift pie chart, error type breakdown, weekly bar chart |
| Stock Detail | `/stock/{ticker}` | KPI grid, 1-year Plotly price chart, thesis + risk + catalyst |

---

## 9. Key Files

```
investment-analyzer/
├── CLAUDE.md
├── business_case/
│   ├── PRD.md
│   ├── business_case.md
│   └── user_research.md
├── start.sh                     ← Railway startup: init DB → first-run agent (if empty) → scheduler → dashboard
├── requirements.txt
├── .gitignore                   ← Excludes .env, *.db, .claude/, .edgar/
├── .project/
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── architecture.md
│   ├── railway.toml
│   ├── scaffold.md
│   └── templates/
├── agent/
│   ├── researcher.py            # Data fetching + Claude thesis generation
│   ├── self_corrector.py        # Prior week diff + Claude correction
│   └── portfolio_manager.py    # Claude buy/sell decisions + trade execution
├── logic/
│   ├── screener.py              # Quant scoring + sector-relative ranking (no LLM)
│   └── evaluations/            # Deterministic output quality checks for LLM agents
├── tools/
│   ├── finnhub_client.py
│   ├── edgar_client.py
│   ├── news_client.py
│   ├── reddit_client.py
│   └── sec_xbrl_client.py
├── workflows/
│   ├── run_weekly.py            # Weekly orchestrator (screener → researcher → self-corrector)
│   ├── run_daily.py             # Daily orchestrator (screener → researcher → portfolio manager)
│   └── dashboard/
│       ├── server.py            # FastAPI backend + API routes
│       └── static/
│           ├── index.html
│           ├── portfolio.html
│           ├── stock.html
│           ├── corrections.html
│           └── accuracy.html
├── memory/
│   ├── database.py              # SQLite schema + CRUD (5 tables)
│   ├── watchlist.json           # 70 curated S&P 500 tickers
│   └── investment_analyzer.db  # SQLite DB (gitignored, persisted via Railway volume)
└── prompts/
    ├── thesis_prompt.txt
    ├── correction_prompt.txt
    └── portfolio_prompt.txt
```

---

## 10. Run Commands

```bash
# Initialize DB + seed watchlist
python3 -m memory.database

# Daily paper trading (V2)
python3 -m workflows.run_daily --dry-run     # screener only, no trades
python3 -m workflows.run_daily --force       # full run regardless of weekday
python3 -m workflows.run_daily --schedule    # APScheduler, weekdays 12:00 noon

# Weekly research (V1)
python3 -m workflows.run_weekly --dry-run
python3 -m workflows.run_weekly --ticker CVS INTC BA
python3 -m workflows.run_weekly

# Local dashboard
python3 -m workflows.dashboard.server   # http://localhost:8080

# Deploy to Railway
railway up --detach
```

---

## 11. Deployment (Railway)

### Live URL
`https://investment-analyzer-production.up.railway.app`

### Infrastructure
| Component | Config |
|-----------|--------|
| Platform | Railway (Hobby plan) |
| GitHub | `github.com/sail1204/investment-analyzer` |
| Build | Nixpacks (auto-detects Python) |
| Start command | `bash start.sh` |
| Volume | `/app/memory` — persists SQLite across deploys |
| DB path | `/app/memory/investment_analyzer.db` (set via `DB_PATH` env var) |

### Environment Variables (set in Railway)
```
ANTHROPIC_API_KEY   = sk-ant-...
FINNHUB_API_KEY     = d6hk1...
DB_PATH             = /app/memory/investment_analyzer.db
SCHEDULER_TZ        = Asia/Kolkata
```

### Startup Sequence (`start.sh`)
1. `python3 -m memory.database` — init DB schema + seed watchlist (idempotent)
2. If portfolio is empty → run `workflows.run_daily --force` (first-deploy auto-invest)
3. `workflows.run_daily --schedule &` — background scheduler (weekdays noon IST)
4. `workflows.dashboard.server` — FastAPI foreground process (Railway health-checks this)

### Deploy on Code Change
```bash
git add .
git commit -m "your change"
railway up --detach     # or push to GitHub if GitHub source is connected
```

### Data Safety
Railway volumes are independent of container deployments. The SQLite file at `/app/memory/investment_analyzer.db` survives all redeploys and restarts. The `start.sh` portfolio-count check prevents the agent from re-running (and re-investing) on restart.

---

## 12. Critical Bug Fixes Applied

| Bug | Fix |
|-----|-----|
| `edgartools` v5 pyarrow AttributeError | Use `filings.to_pandas()` instead of `filings[0]` |
| Python `.format()` KeyError from scraped data | Use token replacement loop — scraped data contains literal `{...}` |
| Finnhub 429 rate limit on stocks 60-70 | `time.sleep(1.1)` between each stock fetch |
| Screener: solo-sector stocks scored 0 | Return 50.0 when `len(valid) <= 1` |
| Plotly chart rendering in corner | Use plain `width:100%; height:Npx` div — `display:flex` constrains Plotly width |
| Row click navigation (Streamlit/NiceGUI) | Switched to FastAPI + native `onclick="window.location='/stock/TICKER'"` |
| 1W Change showing green for null values | `chgColor` now null-checked before applying color |
| Railway `railway run` can't access volume | Volume only accessible inside deployed container, not via `railway run` locally |
| APScheduler timezone defaulting to UTC | `SCHEDULER_TZ` env var + `pytz` — scheduler fires at noon in configured timezone |
| GitHub push blocked by secret scanning | Removed `.claude/settings.json` from git (added `.claude/` to `.gitignore`) |

---

## 13. Future Considerations

- Connect GitHub repo as Railway source (requires one-time browser OAuth in Railway dashboard) for true auto-deploy on `git push`
- Add earnings call transcript parsing (Finnhub paid tier)
- Add analyst earnings revision tracking (Financial Modeling Prep)
- Email/Slack notification on daily trade decisions
- Add a `/admin/run-now` endpoint for manual agent triggers without CLI access
- Bear Case Generator — explicitly steelman the opposite thesis for each stock
- Export weekly reports as PDF
- Add position sizing based on conviction score (higher conviction → larger allocation)
