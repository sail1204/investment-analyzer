"""
SEC EDGAR data client — 10-K, 10-Q, 8-K filings via edgartools.
Free, official API. Rate limit: 10 requests/second.
"""

import gc
import os
import time
import logging
from datetime import date, timedelta
from typing import Optional

# On Railway (512 MB), loading full 10-Q documents causes OOM kills.
# Skip MDA (and optionally all EDGAR) in low-memory environments.
_SKIP_MDA   = bool(os.getenv("EDGAR_SKIP_MDA") or os.getenv("RAILWAY_ENVIRONMENT"))
_SKIP_EDGAR = bool(os.getenv("EDGAR_SKIP"))  # full skip, manual only

# Max 8-K filings to convert to pandas — limits memory on large companies.
_MAX_8K_FILINGS = int(os.getenv("EDGAR_MAX_8K", "4"))

logger = logging.getLogger(__name__)

# Map ticker → CIK using the EDGAR company search endpoint
# edgartools handles this internally via edgar.find_company()


def _get_company(ticker: str):
    """Returns an edgartools Company object or None."""
    try:
        import edgar
        edgar.set_identity("Investment Analyzer research@example.com")
        company = edgar.Company(ticker)
        return company
    except Exception as e:
        logger.warning(f"[EDGAR] Could not find company for {ticker}: {e}")
        return None


def get_recent_8k_summaries(ticker: str, days: int = 30) -> list[dict]:
    """
    Fetch recent 8-K filings (material events) for a ticker.
    Returns list of dicts with: date, description, items.
    """
    company = _get_company(ticker)
    if not company:
        return []

    try:
        filings = company.get_filings(form="8-K")
        # Slice to _MAX_8K_FILINGS before to_pandas() to limit memory usage.
        # edgartools stores filings newest-first so [:N] gives the most recent N.
        df = filings[:_MAX_8K_FILINGS].to_pandas()
        cutoff = date.today() - timedelta(days=days)
        results = []

        for _, row in df.iterrows():
            filing_date_raw = row.get("filing_date")
            if filing_date_raw is None:
                continue
            if isinstance(filing_date_raw, str):
                from datetime import datetime
                filing_date = datetime.strptime(filing_date_raw[:10], "%Y-%m-%d").date()
            elif hasattr(filing_date_raw, "date"):
                filing_date = filing_date_raw.date()
            else:
                filing_date = filing_date_raw

            if filing_date < cutoff:
                continue

            results.append({
                "date":        filing_date.isoformat(),
                "form":        "8-K",
                "description": str(row.get("primaryDocDescription") or row.get("items") or ""),
                "items":       str(row.get("items") or ""),
            })
            if len(results) >= _MAX_8K_FILINGS:
                break

        return results
    except Exception as e:
        logger.warning(f"[EDGAR] 8-K fetch failed for {ticker}: {e}")
        return []


def get_latest_10q_mda(ticker: str) -> Optional[str]:
    """
    Extract the Management Discussion & Analysis section from the latest 10-Q.
    Returns a text string (may be long — caller should truncate to ~2000 chars).
    """
    company = _get_company(ticker)
    if not company:
        return None

    try:
        filings = company.get_filings(form="10-Q")
        if not filings:
            return None

        df = filings.to_pandas()
        if df.empty:
            return None
        accession = df.iloc[0]["accession_number"]
        latest = filings.get(accession)
        doc = latest.obj()

        # edgartools exposes sections via .sections for XBRL-based filings
        mda_text = None
        try:
            if hasattr(doc, "management_discussion_and_analysis"):
                mda_text = str(doc.management_discussion_and_analysis)[:2000]
            elif hasattr(doc, "mda"):
                mda_text = str(doc.mda)[:2000]
            elif hasattr(doc, "text"):
                mda_text = str(doc.text)[:2000]
        finally:
            del doc
            gc.collect()

        return mda_text
    except Exception as e:
        logger.warning(f"[EDGAR] 10-Q MDA failed for {ticker}: {e}")
        return None


def get_latest_10k_risk_factors(ticker: str) -> Optional[str]:
    """
    Extract Risk Factors section from the latest 10-K.
    Useful for understanding what management considers the key risks.
    """
    company = _get_company(ticker)
    if not company:
        return None

    try:
        filings = company.get_filings(form="10-K")
        if not filings:
            return None

        latest = filings[0]
        doc = latest.obj()

        risk_text = None
        if hasattr(doc, "risk_factors"):
            risk_text = doc.risk_factors
        elif hasattr(doc, "item_1a"):
            risk_text = doc.item_1a

        if risk_text:
            return str(risk_text)[:3000]

        return None
    except Exception as e:
        logger.warning(f"[EDGAR] 10-K risk factors failed for {ticker}: {e}")
        return None


def get_filing_summary(ticker: str, days_back: int = 30) -> dict:
    """
    Convenience: get all recent EDGAR data for a ticker.
    Returns a summary dict with 8-K events and 10-Q MDA excerpt.
    On Railway (_SKIP_EDGAR=True) returns empty stubs to avoid OOM.
    """
    if _SKIP_EDGAR:
        logger.debug(f"[EDGAR] Skipping all EDGAR calls for {ticker} (EDGAR_SKIP=1)")
        return {
            "recent_8k_events": [],
            "recent_8k_text":   "EDGAR data skipped.",
            "mda_excerpt":      "10-Q MDA skipped.",
        }

    recent_8ks = get_recent_8k_summaries(ticker, days=days_back)
    time.sleep(0.2)
    mda = None if _SKIP_MDA else get_latest_10q_mda(ticker)

    events_text = ""
    if recent_8ks:
        events_text = "\n".join(
            f"- {e['date']}: {e['description']}" for e in recent_8ks
        )
    else:
        events_text = "No material events (8-K filings) in the past 30 days."

    return {
        "recent_8k_events": recent_8ks,
        "recent_8k_text":   events_text,
        "mda_excerpt":      mda or "10-Q MDA not available.",
    }


if __name__ == "__main__":
    result = get_filing_summary("AAPL")
    print("=== Recent 8-K Events ===")
    print(result["recent_8k_text"])
    print("\n=== 10-Q MDA Excerpt ===")
    print(result["mda_excerpt"][:500])
