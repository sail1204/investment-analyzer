"""
FastAPI backend for Investment Analyzer dashboard.
Serves JSON APIs + static HTML pages.
"""

import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.database import (
    get_all_corrections,
    get_all_snapshots_for_run,
    get_available_run_dates,
    get_ticker_history,
    get_portfolio,
    get_portfolio_history,
    get_transactions,
    get_cash_balance,
    init_db,
)

init_db()

app = FastAPI(title="Investment Analyzer API")

STATIC_DIR = Path(__file__).parent / "static"

# ── Price cache ────────────────────────────────────────────────────────────────
_price_cache: dict = {}


def _fetch_price_history(ticker: str) -> list[dict]:
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        import yfinance as yf
        data = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            _price_cache[ticker] = []
            return []
        data = data.reset_index()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        result = [
            {"date": str(r["Date"])[:10], "close": round(float(r["Close"]), 2)}
            for _, r in data[["Date", "Close"]].dropna().iterrows()
        ]
        _price_cache[ticker] = result
        return result
    except Exception:
        _price_cache[ticker] = []
        return []


# ── API routes ─────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def api_summary():
    dates = get_available_run_dates()
    if not dates:
        return []
    rows = get_all_snapshots_for_run(dates[0])

    corrections = get_all_corrections() or []
    drift_map: dict[str, str] = {}
    if corrections:
        df = pd.DataFrame(corrections).sort_values("run_date")
        drift_map = df.groupby("ticker")["drift_signal"].last().to_dict()

    for r in rows:
        r["drift"] = drift_map.get(r["ticker"], "New")
    return rows


@app.get("/api/stock/{ticker}")
def api_stock(ticker: str):
    dates = get_available_run_dates()
    if not dates:
        return {}
    rows = get_all_snapshots_for_run(dates[0])
    snapshot = next((r for r in rows if r["ticker"] == ticker), None)
    if not snapshot:
        return {}

    corrections = [c for c in (get_all_corrections() or []) if c["ticker"] == ticker]
    history = get_ticker_history(ticker)
    return {"snapshot": snapshot, "corrections": corrections, "history": history}


@app.get("/api/price-history/{ticker}")
def api_price_history(ticker: str):
    return _fetch_price_history(ticker)


@app.get("/api/corrections")
def api_corrections():
    return get_all_corrections() or []


@app.get("/api/portfolio")
def api_portfolio():
    positions = get_portfolio()
    cash = get_cash_balance()
    invested_value = sum(
        p.get("current_value") or p["points_invested"] for p in positions
    )
    total_value = round(cash + invested_value, 2)
    return {
        "positions":      positions,
        "cash":           round(cash, 2),
        "invested_value": round(invested_value, 2),
        "total_value":    total_value,
    }


@app.get("/api/portfolio/history")
def api_portfolio_history():
    return get_portfolio_history() or []


@app.get("/api/transactions")
def api_transactions():
    return get_transactions(limit=500) or []


# ── HTML page routes ───────────────────────────────────────────────────────────

@app.get("/")
def page_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/stock/{ticker}")
def page_stock(ticker: str):
    return FileResponse(STATIC_DIR / "stock.html")


@app.get("/corrections")
def page_corrections():
    return FileResponse(STATIC_DIR / "corrections.html")


@app.get("/accuracy")
def page_accuracy():
    return FileResponse(STATIC_DIR / "accuracy.html")


@app.get("/portfolio")
def page_portfolio():
    return FileResponse(STATIC_DIR / "portfolio.html")


# Mount static assets (CSS overrides, any future assets)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("dashboard.server:app", host="0.0.0.0", port=port, reload=False)
