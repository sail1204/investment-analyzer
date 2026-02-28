"""
Self-Corrector — compares current week's snapshots against prior week,
generates a Claude-authored correction narrative, and logs the result.
"""

import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import anthropic

from sources.edgar_client import get_filing_summary
from sources.news_client import get_stock_news, format_headlines_for_prompt

logger = logging.getLogger(__name__)

CORRECTION_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "correction_prompt.txt"

CORRECTION_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS       = 768


def _load_prompt_template() -> str:
    return CORRECTION_PROMPT_PATH.read_text()


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment")
    return anthropic.Anthropic(api_key=api_key)


def _format_val(val, suffix: str = "", default: str = "N/A") -> str:
    if val is None:
        return default
    try:
        return f"{float(val):.1f}{suffix}"
    except (TypeError, ValueError):
        return default


def _compute_price_change(current_price: Optional[float], prior_price: Optional[float]) -> Optional[float]:
    if current_price is None or prior_price is None or prior_price == 0:
        return None
    return round(((current_price - prior_price) / prior_price) * 100, 2)


def _call_claude(prompt: str, client: anthropic.Anthropic) -> dict:
    message = client.messages.create(
        model      = CORRECTION_MODEL,
        max_tokens = MAX_TOKENS,
        system     = "You are a financial analyst reviewing your prior work. Output valid JSON only.",
        messages   = [{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


def correct_single_stock(
    current_snapshot: dict,
    prior_snapshot: dict,
    client: anthropic.Anthropic,
) -> dict:
    """
    Generate a correction entry for one stock by comparing
    the current snapshot against the prior week's snapshot.

    Returns a correction_log dict.
    """
    ticker       = current_snapshot["ticker"]
    company_name = current_snapshot.get("company_name", ticker)
    logger.info(f"[SelfCorrector] Correcting {ticker}")

    # Compute price change
    price_change = _compute_price_change(
        current_snapshot.get("price"),
        prior_snapshot.get("price"),
    )

    # Fetch new EDGAR events since prior run
    today   = date.today()
    from_dt = (today - timedelta(days=7)).isoformat()
    edgar   = get_filing_summary(ticker, days_back=7)
    time.sleep(0.2)

    # Fetch new headlines
    news_articles = get_stock_news(ticker, company_name, max_results=5)
    headlines_text = format_headlines_for_prompt(news_articles)
    time.sleep(0.3)

    substitutions = {
        "{ticker}":                   ticker,
        "{company_name}":             company_name,
        "{prior_run_date}":           prior_snapshot.get("run_date", "prior week"),
        "{prior_thesis}":             prior_snapshot.get("thesis", "No prior thesis."),
        "{prior_conviction}":         str(prior_snapshot.get("conviction", "N/A")),
        "{prior_valuation_signal}":   str(prior_snapshot.get("valuation_signal", "N/A")),
        "{current_run_date}":         current_snapshot.get("run_date", "current week"),
        "{price_change_pct}":         _format_val(price_change),
        "{current_price}":            _format_val(current_snapshot.get("price")),
        "{new_edgar_events}":         edgar["recent_8k_text"],
        "{new_headlines}":            headlines_text,
        "{prior_pe}":                 _format_val(prior_snapshot.get("pe_ratio"), "x"),
        "{current_pe}":               _format_val(current_snapshot.get("pe_ratio"), "x"),
        "{prior_ev_ebitda}":          _format_val(prior_snapshot.get("ev_ebitda"), "x"),
        "{current_ev_ebitda}":        _format_val(current_snapshot.get("ev_ebitda"), "x"),
        "{prior_fcf_yield}":          _format_val(prior_snapshot.get("fcf_yield")),
        "{current_fcf_yield}":        _format_val(current_snapshot.get("fcf_yield")),
    }

    prompt = _load_prompt_template()
    for token, value in substitutions.items():
        prompt = prompt.replace(token, str(value))

    try:
        llm_out = _call_claude(prompt, client)
    except json.JSONDecodeError as e:
        logger.warning(f"[SelfCorrector] JSON parse failed for {ticker}: {e}")
        llm_out = {
            "drift_signal":      "Stable",
            "error_type":        None,
            "explanation":       "Self-correction parsing failed.",
            "updated_thesis":    prior_snapshot.get("thesis", ""),
            "updated_conviction": prior_snapshot.get("conviction"),
        }
    except Exception as e:
        logger.warning(f"[SelfCorrector] Claude call failed for {ticker}: {e}")
        llm_out = {
            "drift_signal":      "Stable",
            "error_type":        None,
            "explanation":       f"Self-correction failed: {e}",
            "updated_thesis":    prior_snapshot.get("thesis", ""),
            "updated_conviction": prior_snapshot.get("conviction"),
        }

    # Build what_happened summary
    price_str = f"Price moved {price_change:+.1f}%" if price_change is not None else "Price change unknown."
    what_happened = f"{price_str}. {edgar['recent_8k_text'][:300]}"

    correction = {
        "run_date":                 current_snapshot["run_date"],
        "ticker":                   ticker,
        "prior_thesis":             prior_snapshot.get("thesis"),
        "what_happened":            what_happened,
        "agents_explanation":       llm_out.get("explanation"),
        "drift_signal":             llm_out.get("drift_signal"),
        "error_type":               llm_out.get("error_type"),
        "was_directionally_correct": None,  # evaluated later at 4-week lag
    }

    # Also update the current snapshot's thesis and conviction from correction output
    updated_thesis     = llm_out.get("updated_thesis")
    updated_conviction = llm_out.get("updated_conviction")

    if updated_thesis:
        current_snapshot["thesis"] = updated_thesis
    if updated_conviction is not None:
        current_snapshot["conviction"] = updated_conviction

    # Increment thesis_age_weeks: if Stable/Updated, increment; if Contradicted, reset to 1
    if llm_out.get("drift_signal") == "Contradicted":
        current_snapshot["thesis_age_weeks"] = 1
    else:
        prior_age = prior_snapshot.get("thesis_age_weeks", 1) or 1
        current_snapshot["thesis_age_weeks"] = prior_age + 1

    # Update price_change_1w on the snapshot
    current_snapshot["price_change_1w"] = price_change

    return correction


def run_self_corrector(
    current_snapshots: list[dict],
    run_date: str,
) -> list[dict]:
    """
    Run self-correction for all stocks that have a prior week snapshot.

    Args:
        current_snapshots: list of snapshot dicts from researcher
        run_date: current ISO week string ('YYYY-WW')

    Returns:
        list of correction_log dicts ready for DB insertion.
        Also mutates current_snapshots in-place (updates thesis, conviction, price_change_1w).
    """
    from data.database import get_prior_snapshot

    client = _get_anthropic_client()
    corrections = []

    for i, snapshot in enumerate(current_snapshots):
        ticker = snapshot["ticker"]
        prior  = get_prior_snapshot(ticker, run_date)

        if prior is None:
            logger.info(f"[SelfCorrector] {ticker} — no prior snapshot (first week). Skipping correction.")
            continue

        logger.info(f"[SelfCorrector] {i+1}/{len(current_snapshots)} — {ticker}")
        correction = correct_single_stock(snapshot, prior, client)
        corrections.append(correction)
        time.sleep(0.8)

    logger.info(f"[SelfCorrector] Done. Generated {len(corrections)} corrections.")
    return corrections


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from dotenv import load_dotenv
    load_dotenv()

    # Quick test with mock data
    mock_current = {
        "run_date": "2026-10",
        "ticker": "CVS",
        "company_name": "CVS Health Corp.",
        "price": 59.80,
        "pe_ratio": 8.9,
        "ev_ebitda": 7.2,
        "fcf_yield": 8.4,
        "thesis": "CVS appears undervalued at 8.9x earnings...",
        "conviction": 6,
        "valuation_signal": "Cheap",
        "thesis_age_weeks": 1,
    }
    mock_prior = {
        "run_date": "2026-09",
        "ticker": "CVS",
        "company_name": "CVS Health Corp.",
        "price": 62.50,
        "pe_ratio": 9.2,
        "ev_ebitda": 7.5,
        "fcf_yield": 8.1,
        "thesis": "CVS trades at a 30% discount to healthcare peers on FCF yield...",
        "conviction": 7,
        "valuation_signal": "Cheap",
        "thesis_age_weeks": 1,
    }

    client = _get_anthropic_client()
    correction = correct_single_stock(mock_current, mock_prior, client)
    print(json.dumps(correction, indent=2))
