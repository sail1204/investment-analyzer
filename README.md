# Investment Analyzer — AI-Powered Stock Research & Paper Trading

**Live:** https://investment-analyzer-production.up.railway.app

---

## What Is This?

Investment Analyzer is a personal AI system that does two things:

1. **V1 — Weekly Research Agent:** Watches 70 S&P 500 stocks every week, generates investment theses using real data, then *reviews its own prior reasoning* the following week to check whether it was right.

2. **V2 — Daily Paper Trading Agent:** Manages a real (paper) 1,000-point portfolio, making actual buy and sell decisions every weekday at noon using Claude Sonnet.

Most stock screeners give you a score. This system shows you the *reasoning* behind the score — and then holds itself accountable to that reasoning week over week.

---

## Why Build This?

Three problems with how most people research stocks:

- **No reasoning trail.** Screeners show you P/E ratios but not *why* a low P/E might matter for a specific company right now.
- **No accountability.** When an analyst says "this is cheap," there's no mechanism to check back in 4 weeks and ask: was that right? Why not?
- **No separation of signal from noise.** Earnings surprises, macro shocks, and bad thesis construction all look the same in a P&L.

This system is built to solve all three. Every thesis is stored. Every correction is logged. Every trade has a reason attached to it.

---

## The Two Agents

### V1 — Weekly Research Pipeline

Runs every Monday at 6:00 AM. Three steps:

```
70 stocks in watchlist
      │
      ▼
┌──────────────┐     ┌────────────────┐     ┌──────────────────┐
│   Screener   │────▶│   Researcher   │────▶│  Self-Corrector  │
│  (no LLM,    │     │  (top 20-30,   │     │  (prior week     │
│  pure quant) │     │  Claude Sonnet)│     │   diff, Haiku)   │
└──────────────┘     └────────────────┘     └──────────────────┘
```

**Step 1 — Screener (No AI)**
Every stock in the watchlist gets a quantitative score based on:
- How cheap it is *relative to its sector peers* (P/E, EV/EBITDA percentile)
- Quality signals: free cash flow yield, return on equity, interest coverage
- Momentum: 52-week price change (to avoid value traps with no catalyst)

The top 20-30 stocks by composite score move to the next step. The screener uses no AI — it's pure math, sector-relative ranking. This matters because a bank trading at P/E 12 is different from a tech stock at P/E 12.

**Step 2 — Researcher (Claude Sonnet)**
For each screener candidate, the agent pulls real data:
- **Finnhub:** P/E, P/B, EV/EBITDA, FCF yield, ROE, debt-to-equity ratios
- **SEC EDGAR:** Recent 8-K filings (material events) + 10-Q management discussion sections
- **Google News RSS:** Last 5 headlines per stock

Claude then generates an investment thesis answering: *Why does this stock appear undervalued? What is the market mispricing? What is the key variable to watch?*

This is not a simple "P/E is low, buy it." The thesis considers second-order effects — macro factors, sector dynamics, competitor signals — to explain *why* the price might not reflect fair value.

Each thesis is stored with a conviction score (1–10) and a valuation signal (Cheap / Fair / Expensive).

**Step 3 — Self-Corrector (Claude Haiku)**
This is the part most stock research tools skip entirely.

The following week, for every stock researched last week, the agent:
1. Loads last week's thesis from the database
2. Measures what actually happened: price change, new filings, news events
3. Asks Claude: *Did new information confirm or contradict the prior thesis?*

The output is one of four signals:
- **Stable** — thesis holds, nothing material changed
- **Updated** — thesis still directionally correct but needs refinement
- **Contradicted** — the thesis was wrong; new data breaks the core argument
- **Exogenous Shock** — an unpredictable external event invalidated the reasoning (not a thesis error)

When a thesis is wrong, the agent classifies the error type:
- **Exogenous Shock** — earthquake, rate hike, pandemic. Unpredictable. Not a reasoning failure.
- **Timing Error** — right direction, wrong timeframe. The thesis eventually played out.
- **Thesis Error** — fundamentally wrong reasoning. The agent missed something it should have caught.
- **Data Gap** — a key signal was available but not fetched or weighted.

Over time, this correction log becomes a track record. You can see which sectors the agent reasons well about, which error types recur, and whether higher conviction scores actually predict better outcomes.

---

### V2 — Daily Paper Trading Pipeline

Runs every weekday at 12:00 noon IST. Three steps:

```
70 stocks in watchlist
      │
      ▼
┌──────────────┐     ┌────────────────┐     ┌──────────────────────┐
│   Screener   │────▶│   Researcher   │────▶│  Portfolio Manager   │
│  (top 20     │     │  (non-held     │     │  (Claude Sonnet,     │
│   candidates)│     │   stocks only) │     │   buy/sell decisions)│
└──────────────┘     └────────────────┘     └──────────────────────┘
```

**The Portfolio Rules**

| Rule | Value |
|------|-------|
| Starting budget | 1,000 points (1 pt = $1 USD) |
| Position size | 40–200 pts per position |
| Max positions | 20 open at once |
| Min positions | 10 (after initial deployment) |
| Direction | Long only |
| Shares | Fractional: `shares = points_invested / price` |
| Stop-loss guidance | Sell if >15% drawdown from entry |

**How Claude Makes Decisions**

Each day, the portfolio manager gives Claude Sonnet the full picture:
- Current portfolio: every open position with entry price, current price, unrealized P&L, days held
- Cash available
- Today's screener candidates: ranked by value/quality score, with thesis summaries
- Current total portfolio value vs. starting 1,000 pts

Claude responds with a structured JSON decision:
```json
{
  "sells": [{"ticker": "X", "reasoning": "..."}],
  "buys":  [{"ticker": "Y", "points": 75, "reasoning": "..."}],
  "portfolio_commentary": "Brief market/strategy summary"
}
```

Every decision has reasoning attached. Every trade is logged with that reasoning. The transaction log is a full audit trail of Claude's judgment — not just what it did, but why.

**Constraints are enforced in code, not just by the prompt.** Even if Claude returns a buy that would push a position over 200 pts, or exceed 20 positions, the validation layer rejects it. The AI sets strategy; the rules enforce discipline.

---

## Data Sources — What Gets Fed to the Agent and Why

| Source | What It Provides | Why It Matters |
|--------|-----------------|----------------|
| **Finnhub** (free tier) | P/E, P/B, EV/EBITDA, FCF yield, ROE, debt/equity, earnings surprises | The core fundamental signals. Sector-normalized in the screener. |
| **SEC EDGAR** | 10-Q management discussion, 8-K material events | What management is actually saying vs. what the market hears. 8-Ks catch material changes between quarters. |
| **Google News RSS** | Last 5 headlines per stock | Captures narrative shifts that don't show up in fundamentals yet. Macro fear, litigation, product launches. |
| **yfinance** | Live prices for portfolio valuation + 1-year price history | Portfolio mark-to-market. Price chart context for the thesis. |

The agent does not use Reddit PRAW by default (optional, skipped if credentials missing). Social sentiment is noisy and was excluded from the core pipeline.

---

## Dashboard Pages

| Page | What You'll See |
|------|----------------|
| **Summary** (`/`) | All 70 stocks ranked by composite score. Conviction, valuation signal, weekly price change. Click any row for the full thesis. |
| **Portfolio** (`/portfolio`) | Equity curve showing portfolio value over time. Open positions with unrealized P&L. Full transaction history with Claude's reasoning for each trade. |
| **Stock Detail** (`/stock/TICKER`) | 1-year price chart, current fundamentals, Claude's thesis, key risk, catalyst, second-order effects. |
| **Corrections** (`/corrections`) | Every week the agent reviewed its prior thesis. What changed, how the thesis drifted, error classification for wrong calls. |
| **Accuracy** (`/accuracy`) | Drift signal breakdown (Stable/Updated/Contradicted). Error type pie chart. Weekly accuracy bar chart. |

---

## What This System Is Not

- **Not financial advice.** This is a personal research and experimentation tool.
- **Not a real trading system.** V2 uses paper points, not real money. No brokerage connection.
- **Not a prediction engine.** The goal is verifiable reasoning, not a magic signal.
- **Not designed to beat the market.** It's designed to build a track record of *explainable* reasoning — which may or may not outperform an index fund.

---

## How to Run Locally

```bash
# 1. Clone and install
git clone https://github.com/sail1204/investment-analyzer
cd investment-analyzer
pip install -r requirements.txt

# 2. Create .env with your API keys
ANTHROPIC_API_KEY=sk-ant-...
FINNHUB_API_KEY=your_key_here

# 3. Initialize the database
python3 -m data.database

# 4. Run the daily agent (full run)
python3 -m agent.run_daily --force

# 5. Start the dashboard
python3 -m dashboard.server
# Open: http://localhost:8080
```

---

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.11+ | Best data/finance ecosystem |
| LLM (thesis + trades) | Claude Sonnet 4.6 | Best reasoning for financial decisions |
| LLM (corrections) | Claude Haiku 4.5 | Cost-efficient for high-volume weekly correction step |
| Dashboard | FastAPI + vanilla HTML/JS | Switched from Streamlit → NiceGUI → FastAPI; both had row-click navigation bugs that couldn't be reliably fixed |
| Charts | Plotly.js (CDN) | Client-side rendering, no server overhead |
| Database | SQLite | Zero setup, persistent via Railway volume |
| Deployment | Railway | Persistent volume for SQLite, auto-deploy on push |

---

*Built by Sailendra Kumar. Running since February 2026.*

Questions, feedback, or collaboration? Reach out at **sailendra.kumar@gmail.com**
