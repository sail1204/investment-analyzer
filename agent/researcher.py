"""
Researcher — fetches data for each screener candidate and generates
a Claude-authored investment thesis with structured JSON output.
"""

import json
import logging
import os
import statistics
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import anthropic

from logic.evaluations.researcher_eval import evaluate_researcher_output
from memory.database import get_prompt_hints
from tools.edgar_client import get_filing_summary
from tools.finnhub_client import get_earnings_surprises, get_recommendation_trends
from tools.news_client import get_stock_news, format_headlines_for_prompt
from tools.reddit_client import get_reddit_summary

logger = logging.getLogger(__name__)

THESIS_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "thesis_prompt.txt"

# Model for thesis generation — highest quality reasoning
THESIS_MODEL = "claude-sonnet-4-6"
MAX_TOKENS   = 1024
MAX_EVAL_RETRIES = 1


def _load_prompt_template() -> str:
    return THESIS_PROMPT_PATH.read_text()


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment")
    return anthropic.Anthropic(api_key=api_key)


def _compute_sector_medians(all_candidates: list[dict]) -> dict[str, dict]:
    """
    Pre-compute sector median values from all screener candidates.
    Returns: { sector: { pe_median, ev_ebitda_median, fcf_yield_median } }
    """
    sector_groups: dict[str, dict[str, list]] = {}
    for c in all_candidates:
        sector = c.get("sector", "Unknown")
        if sector not in sector_groups:
            sector_groups[sector] = {"pe_ratio": [], "ev_ebitda": [], "fcf_yield": []}
        for key in ["pe_ratio", "ev_ebitda", "fcf_yield"]:
            val = c.get(key)
            if val is not None and val > 0:
                sector_groups[sector][key].append(val)

    medians = {}
    for sector, metrics in sector_groups.items():
        medians[sector] = {
            "pe":       round(statistics.median(metrics["pe_ratio"]), 1)  if metrics["pe_ratio"]  else "N/A",
            "ev_ebitda": round(statistics.median(metrics["ev_ebitda"]), 1) if metrics["ev_ebitda"] else "N/A",
            "fcf_yield": round(statistics.median(metrics["fcf_yield"]), 1) if metrics["fcf_yield"] else "N/A",
        }
    return medians


def _format_learning_hints(agent_name: str, sector: str) -> str:
    hints = get_prompt_hints(
        agent_name,
        [("global", "all"), ("sector", sector)],
        limit=4,
    )
    if not hints:
        return "No persistent learning hints."
    return "\n".join(f"- {row['hint_text']}" for row in hints)


def _format_val(val, suffix: str = "", default: str = "N/A") -> str:
    if val is None:
        return default
    try:
        return f"{float(val):.1f}{suffix}"
    except (TypeError, ValueError):
        return default


def _build_prompt(candidate: dict, sector_medians: dict, news_from: str, news_to: str) -> str:
    """
    Assemble all data sources into the thesis prompt.
    Fetches EDGAR, news, and Reddit data here (side effects).
    """
    ticker       = candidate["ticker"]
    company_name = candidate["company_name"]
    sector       = candidate["sector"]

    # EDGAR data
    edgar = get_filing_summary(ticker, days_back=30)
    time.sleep(0.2)

    # News
    news_articles = get_stock_news(ticker, company_name, max_results=7)
    headlines_text = format_headlines_for_prompt(news_articles)
    time.sleep(0.3)

    # Reddit
    reddit = get_reddit_summary(ticker, company_name)
    time.sleep(0.2)

    # Sector medians
    s_med = sector_medians.get(sector, {})

    # Use simple token replacement instead of .format() — avoids brace collisions
    # with literal { } characters in SEC/news/template content.
    substitutions = {
        "{ticker}":                   ticker,
        "{company_name}":             company_name,
        "{sector}":                   sector,
        "{gics_sub_industry}":        candidate.get("gics_sub_industry", ""),
        "{pe_ratio}":                 _format_val(candidate.get("pe_ratio"), "x"),
        "{pb_ratio}":                 _format_val(candidate.get("pb_ratio"), "x"),
        "{ev_ebitda}":                _format_val(candidate.get("ev_ebitda"), "x"),
        "{roe}":                      _format_val(candidate.get("roe")),
        "{fcf_yield}":                _format_val(candidate.get("fcf_yield")),
        "{debt_equity}":              _format_val(candidate.get("debt_equity"), "x"),
        "{gross_margin}":             _format_val(candidate.get("gross_margin")),
        "{revenue_growth_3y}":        _format_val(candidate.get("revenue_growth_3y")),
        "{w52_return}":               _format_val(candidate.get("52w_return")),
        "{sector_median_pe}":         str(s_med.get("pe", "N/A")),
        "{sector_median_ev_ebitda}":  str(s_med.get("ev_ebitda", "N/A")),
        "{sector_median_fcf_yield}":  str(s_med.get("fcf_yield", "N/A")),
        "{value_score}":              str(candidate.get("value_score", "N/A")),
        "{edgar_events}":             edgar["recent_8k_text"],
        "{mda_excerpt}":              edgar["mda_excerpt"][:1500],
        "{headlines}":                headlines_text,
        "{reddit_summary}":           reddit["prompt_text"],
        "{learning_hints}":           _format_learning_hints("researcher", sector),
    }

    prompt = _load_prompt_template()
    for token, value in substitutions.items():
        prompt = prompt.replace(token, str(value))
    return prompt


def _call_claude(prompt: str, client: anthropic.Anthropic) -> dict:
    """Call Claude and parse the JSON response."""
    message = client.messages.create(
        model      = THESIS_MODEL,
        max_tokens = MAX_TOKENS,
        system     = "You are a disciplined fundamental value investor. Output valid JSON only.",
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


def research_candidate(
    candidate: dict,
    sector_medians: dict,
    run_date: str,
    client: anthropic.Anthropic,
    news_from: str,
    news_to: str,
) -> dict:
    """
    Run the full research pass for a single candidate.
    Returns a snapshot dict ready to be written to stock_snapshots.
    """
    ticker = candidate["ticker"]
    logger.info(f"[Researcher] Researching {ticker}")

    llm_out = None
    try:
        prompt = _build_prompt(candidate, sector_medians, news_from, news_to)
        for attempt in range(MAX_EVAL_RETRIES + 1):
            llm_out = _call_claude(prompt, client)
            evaluation = evaluate_researcher_output(llm_out)
            llm_out = evaluation.normalized_output
            if not evaluation.should_retry:
                break
            logger.warning(
                f"[Researcher] Output eval failed for {ticker} on attempt {attempt + 1}: {evaluation.issues}"
            )
            if attempt >= MAX_EVAL_RETRIES:
                break
    except json.JSONDecodeError as e:
        logger.warning(f"[Researcher] JSON parse failed for {ticker}: {e}")
        llm_out = {
            "thesis":               "Thesis generation failed — JSON parse error.",
            "key_risk":             "N/A",
            "catalyst":             "N/A",
            "second_order_effects": [],
            "conviction":           1,
            "valuation_signal":     "Fair",
        }
    except Exception as e:
        logger.warning(f"[Researcher] Claude call failed for {ticker}: {e}")
        llm_out = {
            "thesis":               f"Thesis generation failed: {e}",
            "key_risk":             "N/A",
            "catalyst":             "N/A",
            "second_order_effects": [],
            "conviction":           1,
            "valuation_signal":     "Fair",
        }

    if llm_out is None:
        llm_out = {
            "thesis":               "Thesis generation failed — no output returned.",
            "key_risk":             "N/A",
            "catalyst":             "N/A",
            "second_order_effects": [],
            "conviction":           1,
            "valuation_signal":     "Fair",
        }

    snapshot = {
        "run_date":           run_date,
        "ticker":             ticker,
        "company_name":       candidate.get("company_name"),
        "sector":             candidate.get("sector"),
        "price":              candidate.get("price"),
        "price_change_1w":    None,  # filled in by self-corrector in subsequent weeks
        "pe_ratio":           candidate.get("pe_ratio"),
        "pb_ratio":           candidate.get("pb_ratio"),
        "ev_ebitda":          candidate.get("ev_ebitda"),
        "roe":                candidate.get("roe"),
        "fcf_yield":          candidate.get("fcf_yield"),
        "debt_equity":        candidate.get("debt_equity"),
        "value_score":        candidate.get("value_score"),
        "quality_score":      candidate.get("quality_score"),
        "conviction":         llm_out.get("conviction"),
        "valuation_signal":   llm_out.get("valuation_signal"),
        "thesis":             llm_out.get("thesis"),
        "key_risk":           llm_out.get("key_risk"),
        "catalyst":           llm_out.get("catalyst"),
        "second_order_effects": json.dumps(llm_out.get("second_order_effects", [])),
        "thesis_age_weeks":   1,
    }
    return snapshot


def run_researcher(candidates: list[dict], run_date: str) -> list[dict]:
    """
    Run the research pass on all screener candidates.

    Args:
        candidates: shortlist from screener (top 20–30 stocks)
        run_date:   current ISO week string ('YYYY-WW')

    Returns:
        list of snapshot dicts ready for DB insertion
    """
    client = _get_anthropic_client()
    today  = date.today()
    news_from = (today - timedelta(days=14)).isoformat()
    news_to   = today.isoformat()

    sector_medians = _compute_sector_medians(candidates)

    snapshots = []
    for i, candidate in enumerate(candidates):
        ticker = candidate["ticker"]
        logger.info(f"[Researcher] {i+1}/{len(candidates)} — {ticker}")
        snapshot = research_candidate(
            candidate, sector_medians, run_date, client, news_from, news_to
        )
        snapshots.append(snapshot)
        time.sleep(1.0)  # avoid rate limits

    logger.info(f"[Researcher] Done. Generated {len(snapshots)} snapshots.")
    return snapshots


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from dotenv import load_dotenv
    load_dotenv()

    from memory.database import current_run_date

    # Quick test with a mock candidate
    mock_candidate = {
        "ticker": "CVS",
        "company_name": "CVS Health Corp.",
        "sector": "Health Care",
        "gics_sub_industry": "Health Care Services",
        "price": 62.50,
        "pe_ratio": 9.2,
        "pb_ratio": 1.1,
        "ev_ebitda": 7.5,
        "roe": 12.3,
        "fcf_yield": 8.1,
        "debt_equity": 1.8,
        "gross_margin": 15.2,
        "revenue_growth_3y": 4.1,
        "52w_return": -22.0,
        "value_score": 78.0,
        "quality_score": 55.0,
        "composite_score": 67.0,
    }

    run_date = current_run_date()
    snapshots = run_researcher([mock_candidate], run_date)
    print(json.dumps(snapshots[0], indent=2))
