"""
Google News RSS client — stock-specific headlines via feedparser.
No API key required. No rate limits.
"""

import time
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
import feedparser

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _build_url(query: str) -> str:
    params = urllib.parse.urlencode({
        "q":   query,
        "hl":  "en-US",
        "gl":  "US",
        "ceid": "US:en",
    })
    return f"{GOOGLE_NEWS_RSS}?{params}"


def _parse_entry(entry) -> dict:
    """Extract clean fields from a feedparser entry."""
    published = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass

    return {
        "title":     getattr(entry, "title", ""),
        "summary":   getattr(entry, "summary", ""),
        "url":       getattr(entry, "link", ""),
        "published": published,
        "source":    getattr(entry, "source", {}).get("title", "") if hasattr(entry, "source") else "",
    }


def get_stock_news(ticker: str, company_name: str, max_results: int = 7) -> list[dict]:
    """
    Fetch recent news for a stock using Google News RSS.
    Searches by both ticker and company name and deduplicates.
    """
    results = []
    seen_titles = set()

    queries = [
        f"{ticker} stock",
        company_name,
    ]

    for query in queries:
        if len(results) >= max_results:
            break
        try:
            url = _build_url(query)
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                item = _parse_entry(entry)
                title_key = item["title"].lower()[:60]
                if title_key and title_key not in seen_titles:
                    seen_titles.add(title_key)
                    results.append(item)
                    if len(results) >= max_results:
                        break
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"[News] RSS fetch failed for '{query}': {e}")

    return results[:max_results]


def get_sector_news(sector: str, max_results: int = 5) -> list[dict]:
    """Fetch sector-level news (used for second-order effects context)."""
    query = f"{sector} sector stocks"
    try:
        url = _build_url(query)
        feed = feedparser.parse(url)
        return [_parse_entry(e) for e in feed.entries[:max_results]]
    except Exception as e:
        logger.warning(f"[News] Sector RSS failed for '{sector}': {e}")
        return []


def format_headlines_for_prompt(articles: list[dict]) -> str:
    """Format news articles into a readable string for LLM prompts."""
    if not articles:
        return "No recent news found."
    lines = []
    for a in articles:
        date_str = a["published"][:10] if a["published"] else "unknown date"
        source = f" ({a['source']})" if a["source"] else ""
        lines.append(f"- [{date_str}]{source} {a['title']}")
    return "\n".join(lines)


if __name__ == "__main__":
    articles = get_stock_news("AAPL", "Apple Inc.")
    for a in articles:
        print(f"{a['published'][:10] if a['published'] else '?'} | {a['title']}")
