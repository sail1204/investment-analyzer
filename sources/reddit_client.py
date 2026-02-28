"""
Reddit PRAW client — sentiment from r/investing and r/stocks.
Free tier: 60 requests/minute with OAuth.
"""

import os
import logging
from typing import Optional
import praw

logger = logging.getLogger(__name__)

SUBREDDITS = ["investing", "stocks"]
_reddit: Optional[praw.Reddit] = None


def get_reddit() -> praw.Reddit:
    global _reddit
    if _reddit is None:
        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        user_agent = os.getenv("REDDIT_USER_AGENT", "investment-analyzer/1.0")

        if not client_id or not client_secret:
            raise ValueError("REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set")

        _reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
    return _reddit


def search_ticker_mentions(ticker: str, company_name: str, limit: int = 20) -> list[dict]:
    """
    Search r/investing and r/stocks for posts mentioning a ticker.
    Returns list of posts with title, score, upvote_ratio, top comment, and url.
    """
    reddit = get_reddit()
    results = []
    seen_ids = set()

    # Search by ticker symbol (with $ prefix is common in these subs)
    queries = [f"${ticker}", ticker, company_name.split()[0]]

    for subreddit_name in SUBREDDITS:
        subreddit = reddit.subreddit(subreddit_name)
        for query in queries[:2]:
            try:
                for post in subreddit.search(query, time_filter="week", limit=limit):
                    if post.id in seen_ids:
                        continue
                    seen_ids.add(post.id)

                    # Get top comment if available
                    top_comment = ""
                    try:
                        post.comments.replace_more(limit=0)
                        if post.comments.list():
                            top_comment = post.comments.list()[0].body[:300]
                    except Exception:
                        pass

                    results.append({
                        "subreddit":    subreddit_name,
                        "title":        post.title,
                        "score":        post.score,
                        "upvote_ratio": post.upvote_ratio,
                        "num_comments": post.num_comments,
                        "url":          f"https://reddit.com{post.permalink}",
                        "top_comment":  top_comment,
                        "created_utc":  post.created_utc,
                    })
            except Exception as e:
                logger.warning(f"[Reddit] Search failed for '{query}' in r/{subreddit_name}: {e}")

    # Sort by score descending, return top 10
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


def summarize_sentiment(posts: list[dict]) -> dict:
    """
    Basic sentiment summary: count bullish/bearish/neutral signals
    based on upvote ratios and scores.
    """
    if not posts:
        return {"post_count": 0, "avg_score": 0, "sentiment": "no data"}

    avg_score = sum(p["score"] for p in posts) / len(posts)
    avg_upvote = sum(p["upvote_ratio"] for p in posts) / len(posts)
    total_comments = sum(p["num_comments"] for p in posts)

    if avg_upvote >= 0.75 and avg_score > 50:
        sentiment = "positive"
    elif avg_upvote <= 0.55 or avg_score < 0:
        sentiment = "negative"
    else:
        sentiment = "mixed"

    return {
        "post_count":     len(posts),
        "avg_score":      round(avg_score, 1),
        "avg_upvote_ratio": round(avg_upvote, 2),
        "total_comments": total_comments,
        "sentiment":      sentiment,
    }


def format_reddit_for_prompt(posts: list[dict], ticker: str) -> str:
    """Format Reddit data into a string for LLM prompts."""
    if not posts:
        return f"No significant Reddit discussion found for {ticker} in the past week."

    lines = [f"Reddit discussion ({len(posts)} posts found, r/investing + r/stocks):"]
    for p in posts[:5]:
        ratio = f"{int(p['upvote_ratio']*100)}% upvoted"
        lines.append(f"- [{p['subreddit']}] \"{p['title']}\" (score: {p['score']}, {ratio})")
        if p["top_comment"]:
            lines.append(f"  Top comment: {p['top_comment'][:150]}...")

    return "\n".join(lines)


def get_reddit_summary(ticker: str, company_name: str) -> dict:
    """
    High-level convenience function.
    Returns posts, sentiment summary, and formatted prompt text.
    Handles missing credentials gracefully.
    """
    try:
        posts = search_ticker_mentions(ticker, company_name)
        sentiment = summarize_sentiment(posts)
        prompt_text = format_reddit_for_prompt(posts, ticker)
        return {"posts": posts, "sentiment": sentiment, "prompt_text": prompt_text}
    except ValueError as e:
        # Missing credentials — return empty gracefully
        logger.info(f"[Reddit] Skipping (credentials not configured): {e}")
        return {
            "posts": [],
            "sentiment": {"post_count": 0, "sentiment": "no data"},
            "prompt_text": "Reddit data not available (API credentials not configured).",
        }
    except Exception as e:
        logger.warning(f"[Reddit] Failed for {ticker}: {e}")
        return {
            "posts": [],
            "sentiment": {"post_count": 0, "sentiment": "no data"},
            "prompt_text": f"Reddit data unavailable for {ticker}.",
        }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    result = get_reddit_summary("AAPL", "Apple Inc.")
    print(result["prompt_text"])
    print("\nSentiment:", result["sentiment"])
