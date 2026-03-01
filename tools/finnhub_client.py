"""
Finnhub data client — fundamentals, company profile, and news.
Free tier: 60 API calls/minute.
"""

import os
import time
import logging
from typing import Optional
import finnhub

logger = logging.getLogger(__name__)

_client: Optional[finnhub.Client] = None


def get_client() -> finnhub.Client:
    global _client
    if _client is None:
        api_key = os.getenv("FINNHUB_API_KEY")
        if not api_key:
            raise ValueError("FINNHUB_API_KEY not set in environment")
        _client = finnhub.Client(api_key=api_key)
    return _client


def get_fundamentals(ticker: str) -> dict:
    """
    Fetch key fundamental metrics for a ticker.
    Returns a flat dict of metrics we care about; None values for missing data.
    """
    client = get_client()
    try:
        data = client.company_basic_financials(ticker, "all")
        metric = data.get("metric", {})

        return {
            "pe_ratio":    metric.get("peNormalizedAnnual"),
            "pb_ratio":    metric.get("pbAnnual"),
            "ev_ebitda":   metric.get("evEbitdaAnnual") or metric.get("evEbitda"),
            "roe":         metric.get("roeAnnual") or metric.get("roe"),
            "fcf_yield":   metric.get("fcfYieldAnnual") or metric.get("freeCashFlowYieldTTM"),
            "debt_equity": metric.get("totalDebt/totalEquityAnnual") or metric.get("longTermDebt/equityAnnual"),
            "revenue_growth_3y": metric.get("revenueGrowth3Y"),
            "gross_margin":      metric.get("grossMarginAnnual") or metric.get("grossMarginTTM"),
            "eps_growth_3y":     metric.get("epsGrowth3Y"),
            "52w_high":          metric.get("52WeekHigh"),
            "52w_low":           metric.get("52WeekLow"),
            "52w_return":        metric.get("52WeekPriceReturnDaily"),
        }
    except Exception as e:
        logger.warning(f"[Finnhub] Fundamentals failed for {ticker}: {e}")
        return {}


def get_price(ticker: str) -> Optional[float]:
    """Fetch current quote price."""
    client = get_client()
    try:
        quote = client.quote(ticker)
        return quote.get("c")  # current price
    except Exception as e:
        logger.warning(f"[Finnhub] Quote failed for {ticker}: {e}")
        return None


def get_price_and_change(ticker: str) -> dict:
    """Return current price and change from previous close."""
    client = get_client()
    try:
        quote = client.quote(ticker)
        current = quote.get("c")
        prev_close = quote.get("pc")
        if current and prev_close and prev_close != 0:
            pct_change = ((current - prev_close) / prev_close) * 100
        else:
            pct_change = None
        return {"price": current, "daily_change_pct": pct_change}
    except Exception as e:
        logger.warning(f"[Finnhub] Quote failed for {ticker}: {e}")
        return {"price": None, "daily_change_pct": None}


def get_company_news(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """
    Fetch recent company news headlines.
    Dates in 'YYYY-MM-DD' format.
    Returns list of dicts with: headline, summary, url, datetime.
    """
    client = get_client()
    try:
        articles = client.company_news(ticker, _from=from_date, to=to_date)
        results = []
        for a in articles[:10]:
            results.append({
                "headline": a.get("headline", ""),
                "summary":  a.get("summary", ""),
                "url":      a.get("url", ""),
                "datetime": a.get("datetime"),
            })
        return results
    except Exception as e:
        logger.warning(f"[Finnhub] News failed for {ticker}: {e}")
        return []


def get_company_profile(ticker: str) -> dict:
    """Fetch company description and sector info."""
    client = get_client()
    try:
        profile = client.company_profile2(symbol=ticker)
        return {
            "name":        profile.get("name"),
            "exchange":    profile.get("exchange"),
            "market_cap":  profile.get("marketCapitalization"),
            "description": profile.get("description", ""),
            "ipo_date":    profile.get("ipo"),
        }
    except Exception as e:
        logger.warning(f"[Finnhub] Profile failed for {ticker}: {e}")
        return {}


def get_earnings_surprises(ticker: str, limit: int = 4) -> list[dict]:
    """Fetch recent earnings surprises (actual vs estimate)."""
    client = get_client()
    try:
        surprises = client.company_earnings(ticker, limit=limit)
        return [
            {
                "period":   s.get("period"),
                "actual":   s.get("actual"),
                "estimate": s.get("estimate"),
                "surprise": s.get("surprise"),
                "surprise_pct": s.get("surprisePercent"),
            }
            for s in (surprises or [])
        ]
    except Exception as e:
        logger.warning(f"[Finnhub] Earnings surprises failed for {ticker}: {e}")
        return []


def get_recommendation_trends(ticker: str) -> Optional[dict]:
    """Get analyst recommendation breakdown (buy/hold/sell counts)."""
    client = get_client()
    try:
        trends = client.recommendation_trends(ticker)
        if trends:
            latest = trends[0]
            return {
                "period":     latest.get("period"),
                "strong_buy": latest.get("strongBuy"),
                "buy":        latest.get("buy"),
                "hold":       latest.get("hold"),
                "sell":       latest.get("sell"),
                "strong_sell": latest.get("strongSell"),
            }
        return None
    except Exception as e:
        logger.warning(f"[Finnhub] Recommendations failed for {ticker}: {e}")
        return None


def fetch_all_for_ticker(ticker: str, news_from: str, news_to: str) -> dict:
    """
    Convenience function: fetch all Finnhub data for a single ticker.
    Adds a small sleep between calls to stay within rate limits.
    """
    result = {"ticker": ticker}
    result["fundamentals"] = get_fundamentals(ticker)
    time.sleep(0.3)

    price_data = get_price_and_change(ticker)
    result["price"] = price_data.get("price")
    result["daily_change_pct"] = price_data.get("daily_change_pct")
    time.sleep(0.3)

    result["news"] = get_company_news(ticker, news_from, news_to)
    time.sleep(0.3)

    result["earnings_surprises"] = get_earnings_surprises(ticker)
    time.sleep(0.3)

    result["recommendations"] = get_recommendation_trends(ticker)
    time.sleep(0.3)

    return result


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from datetime import date, timedelta
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    data = fetch_all_for_ticker("AAPL", week_ago, today.isoformat())
    import json
    print(json.dumps(data, indent=2, default=str))
