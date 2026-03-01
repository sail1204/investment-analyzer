"""
Screener — quantitative scoring and sector-relative ranking.

Scores each stock on:
  - Value score: how cheap is it relative to sector peers?
  - Quality score: profitability and balance sheet strength
  - Composite score: weighted combination

Returns a ranked shortlist of top candidates for deep research.
"""

import logging
import statistics
from typing import Optional

from memory.database import get_learning_state
from tools.finnhub_client import get_fundamentals, get_price_and_change
from tools.sec_xbrl_client import get_companyfacts_metrics

logger = logging.getLogger(__name__)

# ── Scoring weights ──────────────────────────────────────────────────────────
VALUE_WEIGHT   = 0.55
QUALITY_WEIGHT = 0.45

# Metrics used for scoring. The screener treats missing metrics as optional
# and computes averages from whatever is available for each stock.
VALUE_METRICS = {
    "pe_ratio": {"lower_is_better": True, "require_positive": True},
    "pb_ratio": {"lower_is_better": True, "require_positive": True},
    "ev_ebitda": {"lower_is_better": True, "require_positive": True},
}

QUALITY_METRICS = {
    "roe": {"lower_is_better": False, "require_positive": False},
    "fcf_yield": {"lower_is_better": False, "require_positive": False},
    "revenue_growth_yoy": {"lower_is_better": False, "require_positive": False},
    "gross_margin": {"lower_is_better": False, "require_positive": False},
    "gross_margin_delta_1y": {"lower_is_better": False, "require_positive": False},
    "operating_margin": {"lower_is_better": False, "require_positive": False},
    "fcf_margin": {"lower_is_better": False, "require_positive": False},
    "current_ratio": {"lower_is_better": False, "require_positive": True},
    "interest_coverage": {"lower_is_better": False, "require_positive": False},
    "share_count_change_1y": {"lower_is_better": True, "require_positive": False},
}

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


def _metric_usable(value: Optional[float], config: dict) -> bool:
    if value is None:
        return False
    if config.get("require_positive") and value <= 0:
        return False
    return True


def score_stock(metrics: dict, sector_medians: dict) -> dict:
    """
    Compute value_score, quality_score, composite_score for a single stock.
    All scores are 0–100.
    """
    value_scores = []
    for metric, config in VALUE_METRICS.items():
        val = _safe_float(metrics.get(metric))
        peers = sector_medians.get(metric, [])
        if _metric_usable(val, config):
            s = _percentile_rank(val, peers, lower_is_better=config["lower_is_better"])
            value_scores.append(s)

    quality_scores = []
    for metric, config in QUALITY_METRICS.items():
        val = _safe_float(metrics.get(metric))
        peers = sector_medians.get(metric, [])
        if _metric_usable(val, config):
            s = _percentile_rank(val, peers, lower_is_better=config["lower_is_better"])
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
            sector_data[sector] = {
                m: [] for m in list(VALUE_METRICS.keys()) + list(QUALITY_METRICS.keys())
            }

        merged_metrics = {
            **row.get("fundamentals", {}),
            **row.get("sec_metrics", {}),
        }
        metric_configs = {**VALUE_METRICS, **QUALITY_METRICS}
        for metric, config in metric_configs.items():
            val = _safe_float(merged_metrics.get(metric))
            if _metric_usable(val, config):
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

    # Step 1: Fetch fundamentals, price, and SEC metrics for all stocks.
    # Finnhub is still the binding limit here: 2 calls/stock on the free tier.
    # The SEC companyfacts request is free and comfortably within SEC guidance.
    import time as _time
    all_data = []
    for i, stock in enumerate(watchlist):
        ticker = stock["ticker"]
        logger.info(f"[Screener] Fetching {ticker} ({i+1}/{len(watchlist)})")

        fundamentals = get_fundamentals(ticker)
        price_data   = get_price_and_change(ticker)
        sec_metrics  = get_companyfacts_metrics(ticker)

        all_data.append({
            **stock,
            "fundamentals":    fundamentals,
            "sec_metrics":     sec_metrics,
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
        sec = row.get("sec_metrics", {})
        merged_metrics = {**fund, **sec}

        # Anti-value-trap filter
        ret_52w = _safe_float(fund.get("52w_return"))
        if ret_52w is not None and ret_52w < MIN_52W_RETURN:
            logger.info(f"[Screener] {ticker} filtered out: 52W return {ret_52w:.1f}% below threshold")
            continue

        sector = row.get("sector", "Unknown")
        peer_data = sector_peers.get(sector, {})
        scores = score_stock(merged_metrics, peer_data)
        learning_state = get_learning_state("sector_learning", sector) or {}
        learning_penalty = float(learning_state.get("sector_penalty") or 0.0)
        adjusted_composite = max(0.0, scores["composite"] - learning_penalty)

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
            "revenue_growth_yoy": _safe_float(sec.get("revenue_growth_yoy")),
            "gross_margin_sec":   _safe_float(sec.get("gross_margin")),
            "gross_margin_delta_1y": _safe_float(sec.get("gross_margin_delta_1y")),
            "operating_margin":  _safe_float(sec.get("operating_margin")),
            "fcf_margin":        _safe_float(sec.get("fcf_margin")),
            "current_ratio":     _safe_float(sec.get("current_ratio")),
            "interest_coverage": _safe_float(sec.get("interest_coverage")),
            "share_count_change_1y": _safe_float(sec.get("share_count_change_1y")),
            "learning_penalty":  learning_penalty,
            "sector_caution_level": learning_state.get("caution_level", "normal"),
            "value_score":      scores["value_score"],
            "quality_score":    scores["quality_score"],
            "composite_score":  round(adjusted_composite, 1),
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

    from memory.database import get_active_watchlist, init_db, load_watchlist_from_json
    init_db()
    load_watchlist_from_json()

    watchlist = get_active_watchlist()
    # Quick test with just 5 stocks
    results = run_screener(watchlist[:5], top_n=5)
    for r in results:
        print(f"{r['ticker']:6} | composite={r['composite_score']:5.1f} | "
              f"value={r['value_score']:5.1f} | quality={r['quality_score']:5.1f} | "
              f"P/E={r['pe_ratio']}")
