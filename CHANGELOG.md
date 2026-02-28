# Changelog

All notable changes to Investment Analyzer are documented here, newest first.

---

## [2026-02-28] — About & Changes Dashboard Tabs

- Added **About** tab to the dashboard — renders the full README as a styled page
- Added **Changes** tab to the dashboard — this changelog, live in the app
- Added `/api/readme` and `/api/changelog` endpoints in FastAPI backend

---

## [2026-02-28] — PRD & README Written

- Wrote comprehensive `PRD.md` documenting V1 + V2 architecture, deployment, bug fixes, and future considerations
- Wrote user-facing `README.md` explaining the system, the agent pipeline, data sources, and the self-correcting mechanism

---

## [2026-02-28] — Live Deployment on Railway

- Deployed to Railway: [investment-analyzer-production.up.railway.app](https://investment-analyzer-production.up.railway.app)
- Added `start.sh` startup script: DB init → auto-invest on first deploy (if portfolio empty) → background scheduler → FastAPI dashboard
- Added `railway.toml` build config with health-check path
- SQLite data persisted via Railway volume at `/app/data`
- Configured environment variables: `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `DB_PATH`, `SCHEDULER_TZ`
- Fixed APScheduler timezone bug: added `SCHEDULER_TZ` env var + `pytz` — scheduler now fires at noon IST as intended
- Resolved GitHub push protection: moved `.claude/` to `.gitignore` (contained API key)

---

## [2026-02-27] — V2 Paper Trading Agent

- Built `agent/portfolio_manager.py` — Claude Sonnet 4.6 makes daily buy/sell decisions with structured JSON output
- Built `agent/run_daily.py` — daily orchestrator: screener → researcher (non-held only) → portfolio manager
- Added `prompts/portfolio_prompt.txt` — prompt template with portfolio state, screener candidates, and decision rules
- Added 3 new DB tables: `portfolio`, `transactions`, `portfolio_snapshots`
- Built `dashboard/static/portfolio.html` — equity curve, KPI strip, positions table, transaction log
- Added `/api/portfolio`, `/api/portfolio/history`, `/api/transactions` to FastAPI backend
- First investment run: 12 positions deployed (835 pts invested, 165 pts cash)

---

## [2026-02-25] — FastAPI Dashboard Migration

- Migrated dashboard from Streamlit → NiceGUI → **FastAPI + vanilla HTML/JS**
- Root cause for migration: both Streamlit and NiceGUI had persistent row-click navigation bugs that couldn't be reliably fixed; FastAPI with native `onclick="window.location='/stock/TICKER'"` resolved this permanently
- Built 4 dashboard pages: Summary (`/`), Stock Detail (`/stock/{ticker}`), Corrections (`/corrections`), Accuracy (`/accuracy`)
- Added 1-year Plotly.js price chart to Stock Detail page
- Fixed Plotly chart rendering issue: using `width:100%; height:Npx` div — `display:flex` was constraining Plotly width
- Fixed null value color bug: `chgColor` now null-checked before applying green/red class

---

## [2026-02-20] — V1 Weekly Research Agent Complete

- Built `agent/run_weekly.py` — weekly orchestrator: screener → researcher → self-corrector
- Built `agent/self_corrector.py` — diffs prior week's thesis against new data, classifies drift signal (Stable / Updated / Contradicted) and error type (Exogenous Shock / Timing Error / Thesis Error / Data Gap)
- Added `prompts/correction_prompt.txt` — self-correction prompt template
- Added `correction_log` table to SQLite schema

---

## [2026-02-15] — Researcher + LLM Integration

- Built `agent/researcher.py` — fetches fundamentals, SEC filings, news headlines, and calls Claude Sonnet to generate investment thesis
- Added `prompts/thesis_prompt.txt` — thesis generation prompt template
- Added `stock_snapshots` table (PK: run_date + ticker) — stores weekly thesis, conviction (1–10), valuation signal, fundamentals
- Fixed Finnhub rate limit: added `time.sleep(1.1)` between each stock fetch
- Fixed edgartools v5 `pyarrow` AttributeError: use `filings.to_pandas()` instead of `filings[0]`
- Fixed prompt injection risk: use token replacement loop instead of `.format()` — scraped data contains literal `{...}` braces

---

## [2026-02-10] — Screener + Data Sources

- Built `agent/screener.py` — sector-relative quantitative scoring (value score + quality score + momentum), no LLM
- Fixed screener solo-sector bug: returns 50.0 when `len(valid) <= 1` to prevent solo-sector stocks scoring 0
- Built `sources/finnhub_client.py` — fundamentals, earnings surprises, company news via Finnhub free tier
- Built `sources/edgar_client.py` — 10-Q MDA sections and 8-K material events via `edgartools`
- Built `sources/news_client.py` — recent headlines via Google News RSS (`feedparser`)
- Built `sources/reddit_client.py` — r/investing, r/stocks sentiment via PRAW (optional, skipped if credentials missing)

---

## [2026-02-05] — Database + Watchlist

- Built `data/database.py` — SQLite schema init + CRUD helpers (5 tables: watchlist, stock_snapshots, correction_log, portfolio, transactions, portfolio_snapshots)
- Built `data/watchlist.json` — 70 curated S&P 500 stocks across all 11 GICS sectors

---

## [2026-02-01] — Project Started

- Defined V1 (weekly research) and V2 (daily paper trading) architecture
- Selected tech stack: Python 3.11+, FastAPI, SQLite, Claude Sonnet 4.6, Finnhub, SEC EDGAR
- Initialized project structure
