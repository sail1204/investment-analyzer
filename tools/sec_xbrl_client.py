"""
SEC XBRL companyfacts client for free structured financial metrics.

Uses SEC's public JSON APIs:
  - ticker to CIK mapping
  - companyfacts XBRL facts per issuer

The screener uses this client to enrich each stock with a few durable
quality factors that are difficult to get from free market-data APIs.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import requests

logger = logging.getLogger(__name__)

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

DEFAULT_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "Investment Analyzer research@example.com",
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }


def _safe_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct_change(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior in (None, 0):
        return None
    return round(((current - prior) / prior) * 100, 2)


def _latest_fact_values(
    companyfacts: dict,
    taxonomy: str,
    concept_names: list[str],
    *,
    form: str = "10-K",
    max_items: int = 4,
) -> list[float]:
    facts = companyfacts.get("facts", {}).get(taxonomy, {})
    for concept_name in concept_names:
        concept = facts.get(concept_name)
        if not concept:
            continue

        usd_units = concept.get("units", {}).get("USD", [])
        shares_units = concept.get("units", {}).get("shares", [])
        pure_units = concept.get("units", {}).get("pure", [])
        unit_rows = usd_units or shares_units or pure_units
        if not unit_rows:
            continue

        filtered = []
        seen_fy = set()
        for row in unit_rows:
            if row.get("form") != form:
                continue
            fy = row.get("fy")
            value = _safe_float(row.get("val"))
            if fy is None or value is None or fy in seen_fy:
                continue
            seen_fy.add(fy)
            filtered.append((fy, value))

        filtered.sort(key=lambda item: item[0], reverse=True)
        if filtered:
            return [value for _, value in filtered[:max_items]]

    return []


def _latest_instant_value(
    companyfacts: dict,
    taxonomy: str,
    concept_names: list[str],
    *,
    forms: tuple[str, ...] = ("10-Q", "10-K"),
) -> Optional[float]:
    facts = companyfacts.get("facts", {}).get(taxonomy, {})
    for concept_name in concept_names:
        concept = facts.get(concept_name)
        if not concept:
            continue

        usd_units = concept.get("units", {}).get("USD", [])
        pure_units = concept.get("units", {}).get("pure", [])
        unit_rows = usd_units or pure_units
        if not unit_rows:
            continue

        filtered = []
        for row in unit_rows:
            if row.get("form") not in forms:
                continue
            value = _safe_float(row.get("val"))
            filed = row.get("filed", "")
            fy = row.get("fy", 0)
            fp = row.get("fp", "")
            if value is None:
                continue
            filtered.append((filed, fy, fp, value))

        filtered.sort(reverse=True)
        if filtered:
            return filtered[0][3]

    return None


@lru_cache(maxsize=1)
def _ticker_to_cik_map() -> dict[str, str]:
    response = requests.get(SEC_TICKER_URL, headers=_headers(), timeout=20)
    response.raise_for_status()
    data = response.json()

    mapping: dict[str, str] = {}
    for row in data.values():
        ticker = str(row.get("ticker", "")).upper().strip()
        cik = str(row.get("cik_str", "")).zfill(10)
        if ticker and cik:
            mapping[ticker] = cik
    return mapping


@lru_cache(maxsize=256)
def _companyfacts_by_ticker(ticker: str) -> Optional[dict]:
    ticker = ticker.upper().strip()
    cik = _ticker_to_cik_map().get(ticker)
    if not cik:
        logger.warning(f"[SEC XBRL] No CIK mapping found for {ticker}")
        return None

    response = requests.get(
        SEC_COMPANYFACTS_URL.format(cik=cik),
        headers=_headers(),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_companyfacts_metrics(ticker: str) -> dict:
    """
    Return a compact set of SEC-derived screener metrics.

    The output focuses on durable quality and capital-allocation signals.
    Missing concepts are expected; the screener treats missing values as optional.
    """
    try:
        companyfacts = _companyfacts_by_ticker(ticker)
        if not companyfacts:
            return {}

        revenues = _latest_fact_values(
            companyfacts,
            "us-gaap",
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
                "Revenues",
            ],
        )
        gross_profit = _latest_fact_values(companyfacts, "us-gaap", ["GrossProfit"])
        operating_income = _latest_fact_values(companyfacts, "us-gaap", ["OperatingIncomeLoss"])
        operating_cash_flow = _latest_fact_values(
            companyfacts,
            "us-gaap",
            ["NetCashProvidedByUsedInOperatingActivities"],
        )
        capex = _latest_fact_values(
            companyfacts,
            "us-gaap",
            ["PaymentsToAcquirePropertyPlantAndEquipment"],
        )
        diluted_shares = _latest_fact_values(
            companyfacts,
            "us-gaap",
            ["WeightedAverageNumberOfDilutedSharesOutstanding"],
        )

        current_assets = _latest_instant_value(companyfacts, "us-gaap", ["AssetsCurrent"])
        current_liabilities = _latest_instant_value(
            companyfacts,
            "us-gaap",
            ["LiabilitiesCurrent"],
        )
        interest_expense = _latest_fact_values(
            companyfacts,
            "us-gaap",
            [
                "InterestExpenseAndDebtExpense",
                "InterestExpense",
            ],
        )

        latest_revenue = revenues[0] if len(revenues) >= 1 else None
        prior_revenue = revenues[1] if len(revenues) >= 2 else None
        latest_gross_profit = gross_profit[0] if len(gross_profit) >= 1 else None
        prior_gross_profit = gross_profit[1] if len(gross_profit) >= 2 else None
        latest_operating_income = operating_income[0] if len(operating_income) >= 1 else None
        latest_ocf = operating_cash_flow[0] if len(operating_cash_flow) >= 1 else None
        latest_capex = capex[0] if len(capex) >= 1 else None
        latest_interest_expense = abs(interest_expense[0]) if len(interest_expense) >= 1 else None

        gross_margin = (
            round((latest_gross_profit / latest_revenue) * 100, 2)
            if latest_gross_profit is not None and latest_revenue not in (None, 0)
            else None
        )
        prior_gross_margin = (
            round((prior_gross_profit / prior_revenue) * 100, 2)
            if prior_gross_profit is not None and prior_revenue not in (None, 0)
            else None
        )
        operating_margin = (
            round((latest_operating_income / latest_revenue) * 100, 2)
            if latest_operating_income is not None and latest_revenue not in (None, 0)
            else None
        )
        fcf_margin = (
            round(((latest_ocf - abs(latest_capex)) / latest_revenue) * 100, 2)
            if latest_ocf is not None and latest_capex is not None and latest_revenue not in (None, 0)
            else None
        )
        current_ratio = (
            round(current_assets / current_liabilities, 2)
            if current_assets is not None and current_liabilities not in (None, 0)
            else None
        )
        interest_coverage = (
            round(latest_operating_income / latest_interest_expense, 2)
            if latest_operating_income is not None and latest_interest_expense not in (None, 0)
            else None
        )

        share_count_change_1y = None
        if len(diluted_shares) >= 2:
            share_count_change_1y = _pct_change(diluted_shares[0], diluted_shares[1])

        return {
            "revenue_growth_yoy": _pct_change(latest_revenue, prior_revenue),
            "gross_margin": gross_margin,
            "gross_margin_delta_1y": (
                round(gross_margin - prior_gross_margin, 2)
                if gross_margin is not None and prior_gross_margin is not None
                else None
            ),
            "operating_margin": operating_margin,
            "fcf_margin": fcf_margin,
            "current_ratio": current_ratio,
            "interest_coverage": interest_coverage,
            "share_count_change_1y": share_count_change_1y,
        }
    except Exception as exc:
        logger.warning(f"[SEC XBRL] Metrics failed for {ticker}: {exc}")
        return {}
