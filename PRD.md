# Product Requirements Document
# Investment Analyzer — Self-Correcting Stock Research Agent (V1)

**Date:** 2026-02-28
**Status:** Draft
**Author:** Sailendra Kumar

---

## 1. Overview

### Vision
A personal AI-powered investment research agent that observes S&P 500 companies, reasons about why stocks appear undervalued, and self-corrects its own prior reasoning week-over-week. The agent builds a verifiable track record over time — it does not make buy/sell decisions.

### Why Build This
Most stock screeners give you a number. None of them show you the reasoning behind it, whether that reasoning held up, or how it evolved. This agent is designed to fill that gap: a system that watches, reasons, and audits itself — the way a disciplined analyst would.

### Three Use Cases
1. **Personal investing education** — learn by watching the agent reason over time
2. **AI product experimentation** — test how well LLMs do causal financial reasoning
3. **Course / newsletter material** — a real, running system with a real track record to share

---

## 2. V1 Goals

- Screen a curated list of 50–100 S&P 500 stocks weekly using quantitative filters
- For the top candidates, generate an LLM-authored thesis explaining *why* a stock appears undervalued (causal "why is it cheap?" layer)
- Store every weekly snapshot and automatically diff it against the prior week
- Produce a self-correction narrative: did new data confirm or contradict the prior thesis?
- Display everything in a local Streamlit dashboard

## V1 Non-Goals

| Out of scope for V1 | Reason |
|---------------------|--------|
| Buy/sell recommendations | Observation-only phase |
| Real-money portfolio integration | Not needed for track record building |
| Multi-user support | Personal tool |
| Paid APIs | Start free, add later |
| Real-time data | Weekly cadence is sufficient |
| Earnings call transcript parsing | V2 feature |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Weekly Agent Run (Cron/APScheduler)      │
│                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Screener │───▶│  Researcher  │───▶│ Self-Corrector   │  │
│  │ (Quant)  │    │  (LLM+Data)  │    │ (LLM + prev week)│  │
│  └──────────┘    └──────────────┘    └──────────────────┘  │
│       │                │                      │             │
│       ▼                ▼                      ▼             │
│  Ranked shortlist  Stock cards           Correction log     │
│  (top 20–30)       + thesis              + drift signal     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │  SQLite Database │
                    │  (weekly snapshots│
                    │   + thesis log)  │
                    └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ Streamlit        │
                    │ Dashboard        │
                    └──────────────────┘
```

The three agent layers are intentionally separated:

- **Screener** is fast, rule-based, and runs on all 50–100 stocks. No LLM.
- **Researcher** is the expensive LLM pass — only runs on the top 20–30 shortlisted candidates.
- **Self-Corrector** compares new data to last week's output and generates the audit trail.

---

## 4. Data Sources (All Free in V1)

| Source | Purpose | Rate Limit | Python Library |
|--------|----------|-----------|----------------|
| **Finnhub** (free tier) | Fundamentals: P/E, P/B, EV/EBITDA, FCF yield, ROE, debt/equity, company news | 60 calls/min | `finnhub-python` |
| **SEC EDGAR** | 10-K, 10-Q, 8-K filings — management commentary, risk factors, structured XBRL data | 10 req/sec | `edgartools` |
| **Google News RSS** | Recent headlines per stock (no API key needed) | Unlimited | `feedparser` |
| **Reddit PRAW** | Retail sentiment from r/investing, r/stocks | 60 req/min | `praw` |
| **yfinance** | Price history, 1W price change (fallback only) | Unofficial | `yfinance` |

### Important Notes on Data Sources

**Finnhub** is the primary fundamentals source. The free tier (60 calls/min) is sufficient for 100 stocks weekly — all calls complete in under 2 minutes. Covers company financials, sector metrics, and news in one API.

**SEC EDGAR** is the highest-signal free source. Official government data with no authentication required. Key use: pulling 8-K events (material news) and 10-Q management discussion sections. The `edgartools` library handles parsing.

**yfinance:** Only use the `.info` property for quick ratios. The `.financials()`, `.cashflow()`, and `.balance_sheet()` methods return empty dataframes — do not use them. Finnhub is more reliable for actual fundamental data.

---

## 5. Agent Pipeline

### Step 1 — Screener (Quantitative Filter)

**Input:** Curated watchlist of 50–100 tickers (stored in `data/watchlist.json`)

**Process:**
1. Pull fundamentals from Finnhub for each ticker
2. Group tickers by GICS sector
3. Compute sector-relative scores for each stock:
   - **Value score:** Where does P/E and EV/EBITDA rank within sector peers? (bottom 20% = high value score)
   - **Quality score:** FCF yield, ROE, interest coverage ratio
   - **Anti-value-trap filter:** Exclude stocks with >30% decline over 52 weeks unless there's a clear reason
4. Combine into a composite score
5. Rank all stocks; select top 20–30 as "candidates for deep research"

**Output:** Ranked candidate list with raw scores, saved to DB

### Step 2 — Researcher (LLM + Data Scraping)

**Input:** Top 20–30 candidates from Step 1

**Process per stock:**
1. Fetch recent 8-K filings (last 30 days) from SEC EDGAR — material events
2. Fetch the Management Discussion & Analysis section from latest 10-Q
3. Fetch last 5–7 news headlines from Google News RSS
4. Fetch top Reddit mentions from the past week (r/investing + r/stocks)
5. Bundle everything into a context block, pass to Claude API with the Thesis Prompt
6. Parse structured JSON output from Claude: thesis, key risk, catalyst, conviction (1–10), valuation signal, second-order effects

**Output:** Stock card per candidate, written to `stock_snapshots` table

### Step 3 — Self-Corrector (LLM + Prior Week Diff)

**Input:** New stock cards + prior week's cards from SQLite

**Process per stock:**
1. Retrieve last week's thesis, conviction score, valuation signal
2. Calculate: price change %, any new EDGAR filings, new headlines
3. Pass prior thesis + new data to Claude API with the Self-Correction Prompt
4. Parse response: drift signal, error type (if wrong), updated thesis
5. Write correction entry to `correction_log` table

**Drift Signal categories:**
- `Stable` — new data confirms prior thesis
- `Updated` — thesis refined with new information, still directionally same
- `Contradicted` — thesis was directionally wrong

**Error Type categories (when Contradicted):**
- `Exogenous Shock` — new unpredictable event (e.g., regulatory action, CEO resignation)
- `Timing Error` — right direction, wrong timeframe
- `Thesis Error` — fundamentally flawed reasoning
- `Data Gap` — missed a key signal that was available at the time

### Step 4 — Persistence
Write all stock cards, correction log entries, and metadata to SQLite with `run_date` (year + week number).

### Step 5 — Dashboard Refresh
Streamlit reads from SQLite on page load. No live API calls in the dashboard layer.

---

## 6. Data Schema (SQLite)

### Table: `stock_snapshots`

| Column | Type | Description |
|--------|------|-------------|
| `run_date` | TEXT | `YYYY-WW` (year + ISO week number) |
| `ticker` | TEXT | Stock ticker symbol |
| `company_name` | TEXT | Full company name |
| `sector` | TEXT | GICS sector |
| `price` | REAL | Closing price at run time |
| `price_change_1w` | REAL | % price change from prior week |
| `pe_ratio` | REAL | Price-to-Earnings |
| `pb_ratio` | REAL | Price-to-Book |
| `ev_ebitda` | REAL | EV/EBITDA |
| `roe` | REAL | Return on Equity |
| `fcf_yield` | REAL | Free Cash Flow Yield |
| `debt_equity` | REAL | Debt-to-Equity ratio |
| `value_score` | REAL | Composite screener value score |
| `quality_score` | REAL | Composite screener quality score |
| `conviction` | INTEGER | LLM-assigned 1–10 conviction score |
| `valuation_signal` | TEXT | `Cheap` / `Fair` / `Expensive` |
| `thesis` | TEXT | LLM-generated 3–5 sentence narrative |
| `key_risk` | TEXT | Primary risk to the thesis |
| `catalyst` | TEXT | What could resolve the undervaluation |
| `second_order_effects` | TEXT | Macro/sector/competitor signals (JSON) |
| `thesis_age_weeks` | INTEGER | Weeks the current thesis has held |
| PRIMARY KEY | | `(run_date, ticker)` |

### Table: `correction_log`

| Column | Type | Description |
|--------|------|-------------|
| `run_date` | TEXT | Week of this correction |
| `ticker` | TEXT | Stock ticker |
| `prior_thesis` | TEXT | Last week's thesis verbatim |
| `what_happened` | TEXT | Price move + key events since last week |
| `agents_explanation` | TEXT | LLM explanation of the update |
| `drift_signal` | TEXT | `Stable` / `Updated` / `Contradicted` |
| `error_type` | TEXT | NULL or one of the 4 error types |
| `was_directionally_correct` | INTEGER | 1/0/NULL — evaluated at 4-week lag |

### Table: `watchlist`

| Column | Type | Description |
|--------|------|-------------|
| `ticker` | TEXT PRIMARY KEY | Stock ticker |
| `company_name` | TEXT | Full name |
| `sector` | TEXT | GICS sector |
| `gics_sub_industry` | TEXT | GICS sub-industry (for peer comparison) |
| `active` | INTEGER | 1 = tracked, 0 = paused |
| `added_date` | TEXT | When added to watchlist |

---

## 7. Output: Streamlit Dashboard

### Page 1 — Weekly Summary Table
Sortable table across all tracked stocks for the current week:

| Ticker | Company | Sector | Val. Signal | Conviction | 1W Δ | Thesis Drift | Weeks Tracked | 4W Accuracy |
|--------|---------|--------|------------|------------|------|-------------|---------------|-------------|
| MSFT | Microsoft | Tech | Fair | 7 | +2.1% | Stable | 8 | ✓ (4/5) |
| XOM | ExxonMobil | Energy | Cheap | 8 | -1.3% | Updated | 3 | — |
| CVS | CVS Health | Healthcare | Cheap | 5 | -4.2% | Contradicted | 6 | ✗ (2/5) |

- Color-coded: Cheap = green chip, Expensive = red chip, Contradicted = orange flag
- Week selector to browse historical snapshots
- Click any row → opens Stock Detail page

### Page 2 — Stock Detail Card

For the selected stock, displays:

1. **Header row** — Price, 1W change, Conviction (visual gauge), Valuation signal
2. **Fundamentals panel** — Current vs. sector median for each metric (arrows for delta direction)
3. **Agent Thesis** — This week's LLM narrative
4. **What Changed This Week** — The diff: prior thesis excerpt → new information → updated reasoning
5. **Second-Order Flags** — Bullet list (macro factors, sector signals, competitor events)
6. **Thesis History** — Line chart of conviction score over all tracked weeks
7. **Data Sources Used** — Expandable: which EDGAR filings were pulled, headlines used

### Page 3 — Self-Correction Log

Full scrollable log of all correction events across all stocks, with:
- Filters by: drift signal, error type, sector, ticker, date range
- Each row expandable to show full prior thesis, new information, and explanation
- Summary stats at top: % stable / updated / contradicted this week

### Page 4 — Accuracy Tracker *(populates over time)*

Answers the key longitudinal questions:
- Does the agent's conviction score correlate with actual outperformance at 4 weeks?
- Which sectors produce the most accurate theses?
- Which error type is most common? (A well-calibrated agent should show mostly Exogenous Shocks, not Thesis Errors)
- Is accuracy improving week-over-week as prompts are refined?

---

## 8. Prompt Design

### Thesis Prompt (Researcher Step)

```
SYSTEM: You are a disciplined fundamental value investor.
You reason from data to conclusions, never the reverse.
Be specific about what the data shows and what it does not show.
Output must be valid JSON.

STOCK: {ticker} — {company_name} ({sector})

FUNDAMENTALS:
{fundamentals_block}
Sector median comparison:
{sector_median_block}

RECENT SEC FILINGS (last 30 days):
{edgar_summary}

RECENT NEWS HEADLINES:
{headlines}

REDDIT SENTIMENT (r/investing + r/stocks, past week):
{reddit_summary}

TASK:
1. Explain in 3–5 sentences why this stock appears undervalued (or not).
   Ground every claim in the data above — do not speculate.
2. State the single most important variable to watch.
3. Identify 1–2 second-order effects (macro, sector, or competitor signals).
4. Assign a conviction score (1–10) — 1 = no thesis, 10 = very high confidence.
5. Classify as: Cheap / Fair / Expensive.

Output JSON:
{
  "thesis": "...",
  "key_risk": "...",
  "catalyst": "...",
  "second_order_effects": ["...", "..."],
  "conviction": 7,
  "valuation_signal": "Cheap"
}
```

### Self-Correction Prompt (Self-Corrector Step)

```
SYSTEM: You are a financial analyst reviewing your own prior work.
Be intellectually honest. Separate what you knew then from what is known now.
Output must be valid JSON.

PRIOR THESIS (Week {N-1}):
{prior_thesis}

NEW INFORMATION (Week {N}):
- Price change: {price_change_1w}%
- New SEC filings: {new_filings_summary}
- Key news headlines: {headlines}
- Fundamentals change: {metrics_delta}

TASK:
1. State whether the new information CONFIRMS, UPDATES, or CONTRADICTS the prior thesis.
2. If CONTRADICTS — classify the error type:
   - Exogenous Shock: a new, unpredictable event invalidated the thesis
   - Timing Error: right direction, wrong timeframe
   - Thesis Error: fundamentally flawed reasoning given information available at the time
   - Data Gap: missed a key signal that was available at the time
3. Write an updated thesis in 3–5 sentences.

Output JSON:
{
  "drift_signal": "Stable" | "Updated" | "Contradicted",
  "error_type": null | "Exogenous Shock" | "Timing Error" | "Thesis Error" | "Data Gap",
  "explanation": "...",
  "updated_thesis": "..."
}
```

---

## 9. Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.11+ | Best ecosystem for finance/data |
| Dashboard | Streamlit | Rapid iteration, Python-native, no frontend code needed |
| Database | SQLite | Zero setup, sufficient for personal use, easy to inspect |
| LLM (thesis) | Claude Sonnet 4.6 | Best reasoning quality for thesis generation |
| LLM (correction) | Claude Haiku 4.5 | Lower cost for high-volume correction step |
| Scheduler | APScheduler | Simple Python-native weekly scheduler |
| Config | `.env` file | API keys; `watchlist.json` for ticker list |

**Estimated running cost:**
- Finnhub: $0 (free tier, 60 calls/min is sufficient)
- SEC EDGAR: $0 (official free API)
- Claude API: ~25 stocks × ~3,000 tokens × $3/MTok ≈ **~$0.23/week** for thesis generation

---

## 10. Project File Structure

```
investment-analyzer/
├── PRD.md                       ← This document
├── agent/
│   ├── screener.py              # Quantitative scoring + watchlist ranking
│   ├── researcher.py            # Data fetching + LLM thesis generation
│   ├── self_corrector.py        # Prior week diff + LLM self-correction
│   └── run_weekly.py            # Orchestrator — runs all 3 steps in sequence
├── data/
│   ├── database.py              # SQLite schema creation + CRUD helpers
│   ├── watchlist.json           # Curated 50–100 S&P 500 tickers with sector info
│   └── investment_analyzer.db  # SQLite database (gitignored)
├── sources/
│   ├── finnhub_client.py        # Fundamentals + news via Finnhub
│   ├── edgar_client.py          # 10-K, 10-Q, 8-K via edgartools
│   ├── news_client.py           # Google News RSS via feedparser
│   └── reddit_client.py         # r/investing, r/stocks via PRAW
├── dashboard/
│   └── app.py                   # Streamlit app (4 pages)
├── prompts/
│   ├── thesis_prompt.txt        # Researcher LLM prompt template
│   └── correction_prompt.txt    # Self-corrector LLM prompt template
├── .env.example                 # API key template (committed)
├── .env                         # Actual API keys (gitignored)
└── requirements.txt
```

---

## 11. Build Milestones

| Week | Milestone | Deliverable |
|------|-----------|-------------|
| 1 | Foundation | Watchlist setup, all data clients (Finnhub, EDGAR, News, Reddit), SQLite schema |
| 2 | Screener | Quant scoring logic, sector-relative ranking, shortlist output |
| 3 | Researcher | Data fetching per stock + Claude thesis generation, JSON output to DB |
| 4 | First full run | End-to-end `run_weekly.py` completes, inspect DB output manually |
| 5 | Self-Corrector | Prior week diff logic + Claude correction step, correction_log populated |
| 6 | Dashboard V1 | Summary Table + Stock Detail pages live in Streamlit |
| 7 | Dashboard V2 | Correction Log + Accuracy Tracker pages |
| 8 | First review | Manually evaluate 4 weeks of output quality, refine prompts |

---

## 12. Verification Checklist

- [ ] Screener produces a ranked list for 10 known stocks with directionally sensible scores
- [ ] Researcher fetches real data (verify EDGAR filings are not empty, headlines are recent)
- [ ] Thesis output is grounded in fetched data — spot check 5 stocks manually
- [ ] Correction log references actual price changes from the prior week
- [ ] All 4 Streamlit pages load without errors
- [ ] Summary table is sortable by all columns
- [ ] Clicking a row opens the correct Stock Detail card
- [ ] After week 4: manually review whether high-conviction stocks are showing any pattern

---

## 13. Future Considerations (V2+)

- Add earnings call transcript parsing (Finnhub paid tier or EarningsCall.biz free API)
- Add analyst earnings revision tracking (Financial Modeling Prep, ~$15/month)
- Email delivery of weekly report via SendGrid
- Deploy Streamlit to Streamlit Cloud for shareable demo access
- Add a "Bear Case Generator" — explicitly steelman the opposite thesis for each stock
- Export weekly reports as PDF for newsletter / course material
