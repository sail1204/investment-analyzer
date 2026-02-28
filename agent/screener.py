"""
Screener — quantitative scoring and sector-relative ranking.

Scores each stock on:
  - Value score: how cheap is it relative to sector peers?
  - Quality score: profitability and balance sheet strength
  - Composite score: weighted combination

Returns a ranked shortlist of top candidates for deep research.
"""

import json
import logging
import statistics
from datetime import date, timedelta
from typing import Optional

from sources.finnhub_client import get_fundamentals, get_price_and_change

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────────────
VALUE_WEIGHT   = 0.55
QUALITY_WEIGHT = 0.45

# Metrics used for value scoring (lower is better for all of these)
VALUE_METRICS = ["pe_ratio", "pb_ratio", "ev_ebitda"]

# Metrics used for quality scoring (higher is better)
QUALITY_METRICS = ["roe", "fcf_yield"]

# Anti-value-trap filter: exclude if 52-week return is worse than this threshold
MIN_52W_RETURN = -45.0   # % — ignore companies in deep distress


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _percentile_rank(value: float, peer_values: list[float], lower_is_better: bool) -> float:
    """
    Returns a 0–100 score representing how favorable this value is
    relative to peers. 100 = best in group.
    """
    if not peer_values or value is None:
        return 50.0

    valid = [v for v in peer_values if v is not None]
    if len(valid) <= 1:
        return 50.0

    rank = sum(1 for v in valid if v <= value)
    pct = (rank / len(valid)) * 100

    # Flip so that lower value → higher score when lower is better
    return (100 - pct) if lower_is_better else pct


def score_stock(metrics: dict, sector_medians: dict) -> dict:
    """
    Compute value_score, quality_score, composite_score for a single stock.
    All scores are 0–100.
    """
    value_scores = []
    for metric in VALUE_METRICS:
        val = _safe_float(metrics.get(metric))
        peers = sector_medians.get(metric, [])
        if val is not None and val > 0:
            s = _percentile_rank(val, peers, lower_is_better=True)
            value_scores.append(s)

    quality_scores = []
    for metric in QUALITY_METRICS:
        val = _safe_float(metrics.get(metric))
        peers = sector_medians.get(metric, [])
        if val is not None:
            s = _percentile_rank(val, peers, lower_is_better=False)
            quality_scores.append(s)

    value_score   = statistics.mean(value_scores)   if value_scores   else 50.0
    quality_score = statistics.mean(quality_scores) if quality_scores else 50.0
    composite     = (VALUE_WEIGHT * value_score) + (QUALITY_WEIGHT * quality_score)

    return {
        "value_score":   round(value_score, 1),
        "quality_score": round(quality_score, 1),
        "composite":     round(composite, 1),
    }


def build_sector_peer_lists(all_metrics: list[dict]) -> dict[str, dict[str, list[float]]]:
    """
    Group metric values by sector for peer comparison.
    Returns: { sector: { metric_name: [values...] } }
    """
    sector_data: dict[str, dict[str, list]] = {}

    for row in all_metrics:
        sector = row.get("sector", "Unknown")
        if sector not in sector_data:
            sector_data[sector] = {m: [] for m in VALUE_METRICS + QUALITY_METRICS}

        for metric in VALUE_METRICS + QUALITY_METRICS:
            val = _safe_float(row.get("fundamentals", {}).get(metric))
            if val is not None and val > 0:
                sector_data[sector][metric].append(val)

    return sector_data


def run_screener(watchlist: list[dict], top_n: int = 30) -> list[dict]:
    """
    Main screener function.

    Args:
        watchlist: list of dicts from watchlist table (ticker, company_name, sector, ...)
        top_n: number of top candidates to return for deep research

    Returns:
        Sorted list of stock dicts with scores, fundamentals, price data.
        Only returns top_n results.
    """
    logger.info(f"[Screener] Starting screen for {len(watchlist)} stocks")

    # Step 1: Fetch fundamentals and price for all stocks
    # Finnhub free tier: 60 calls/min. Each stock = 2 calls (fundamentals + quote).
    # 70 stocks × 2 = 140 calls — needs ~1.1s/stock to stay safely under limit.
    import time as _time
    all_data = []
    for i, stock in enumerate(watchlist):
        ticker = stock["ticker"]
        logger.info(f"[Screener] Fetching {ticker} ({i+1}/{len(watchlist)})")

        fundamentals = get_fundamentals(ticker)
        price_data   = get_price_and_change(ticker)

        all_data.append({
            **stock,
            "fundamentals":    fundamentals,
            "price":           price_data.get("price"),
            "daily_change_pct": price_data.get("daily_change_pct"),
        })

        _time.sleep(1.1)  # ~55 stocks/min — safely within Finnhub free tier 60 calls/min

    # Step 2: Build sector peer lists
    sector_peers = build_sector_peer_lists(all_data)

    # Step 3: Score each stock
    scored = []
    for row in all_data:
        ticker = row["ticker"]
        fund = row.get("fundamentals", {})

        # Anti-value-trap filter
        ret_52w = _safe_float(fund.get("52w_return"))
        if ret_52w is not None and ret_52w < MIN_52W_RETURN:
            logger.info(f"[Screener] {ticker} filtered out: 52W return {ret_52w:.1f}% below threshold")
            continue

        sector = row.get("sector", "Unknown")
        peer_data = sector_peers.get(sector, {})
        scores = score_stock(fund, peer_data)

        scored.append({
            "ticker":           ticker,
            "company_name":     row.get("company_name"),
            "sector":           sector,
            "gics_sub_industry": row.get("gics_sub_industry"),
            "price":            row.get("price"),
            "daily_change_pct": row.get("daily_change_pct"),
            "pe_ratio":         _safe_float(fund.get("pe_ratio")),
            "pb_ratio":         _safe_float(fund.get("pb_ratio")),
            "ev_ebitda":        _safe_float(fund.get("ev_ebitda")),
            "roe":              _safe_float(fund.get("roe")),
            "fcf_yield":        _safe_float(fund.get("fcf_yield")),
            "debt_equity":      _safe_float(fund.get("debt_equity")),
            "gross_margin":     _safe_float(fund.get("gross_margin")),
            "revenue_growth_3y": _safe_float(fund.get("revenue_growth_3y")),
            "52w_return":       _safe_float(fund.get("52w_return")),
            "value_score":      scores["value_score"],
            "quality_score":    scores["quality_score"],
            "composite_score":  scores["composite"],
        })

    # Step 4: Sort by composite score descending
    scored.sort(key=lambda x: x["composite_score"], reverse=True)

    logger.info(f"[Screener] Scored {len(scored)} stocks. Returning top {top_n}.")
    return scored[:top_n]


def valuation_signal(pe: Optional[float], pb: Optional[float], ev_ebitda: Optional[float],
                     value_score: float) -> str:
    """
    Simple valuation classification based on composite value score.
    """
    if value_score >= 65:
        return "Cheap"
    elif value_score <= 35:
        return "Expensive"
    else:
        return "Fair"


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from dotenv import load_dotenv
    load_dotenv()

    from data.database import get_active_watchlist, init_db, load_watchlist_from_json
    init_db()
    load_watchlist_from_json()

    watchlist = get_active_watchlist()
    # Quick test with just 5 stocks
    results = run_screener(watchlist[:5], top_n=5)
    for r in results:
        print(f"{r['ticker']:6} | composite={r['composite_score']:5.1f} | "
              f"value={r['value_score']:5.1f} | quality={r['quality_score']:5.1f} | "
              f"P/E={r['pe_ratio']}")
