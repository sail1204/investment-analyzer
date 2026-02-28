"""
Portfolio Manager — daily buy/sell decision agent.

Uses Claude Sonnet to review the current portfolio + screener candidates
and make buy/sell decisions within the 1,000-point paper trading budget.
"""

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

PORTFOLIO_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "portfolio_prompt.txt"
PORTFOLIO_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024

MIN_POINTS_PER_POSITION = 40
MAX_POINTS_PER_POSITION = 200
MIN_POSITIONS = 10
MAX_POSITIONS = 20


def _get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=api_key)


def _load_prompt_template() -> str:
    return PORTFOLIO_PROMPT_PATH.read_text()


def _get_current_price(ticker: str) -> Optional[float]:
    """Fetch latest close price from yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        logger.warning(f"[PortfolioMgr] Price fetch failed for {ticker}: {e}")
    return None


def refresh_prices(positions: list[dict]) -> list[dict]:
    """Update current_price, current_value, unrealized_pnl for each position."""
    from data.database import upsert_position

    for pos in positions:
        ticker = pos["ticker"]
        price = _get_current_price(ticker)
        if price is None:
            logger.warning(f"[PortfolioMgr] Skipping price refresh for {ticker}")
            continue

        current_value = round(pos["shares"] * price, 4)
        unrealized_pnl = round(current_value - pos["points_invested"], 4)

        pos["current_price"]  = price
        pos["current_value"]  = current_value
        pos["unrealized_pnl"] = unrealized_pnl

        upsert_position(pos)
        logger.info(f"[PortfolioMgr] {ticker}: ${price:.2f} | "
                    f"value={current_value:.1f} | pnl={unrealized_pnl:+.1f}")
        time.sleep(0.3)

    return positions


def _build_positions_table(positions: list[dict]) -> str:
    if not positions:
        return "(no open positions)"

    today = date.today()
    lines = ["Ticker  | Pts In | Cur Value | P&L%   | Days | Signal",
             "--------|--------|-----------|--------|------|-------"]
    for p in positions:
        buy_date = p.get("buy_date", str(today))
        try:
            days_held = (today - date.fromisoformat(buy_date)).days
        except Exception:
            days_held = 0

        pnl_pts  = p.get("unrealized_pnl") or 0
        pts_in   = p.get("points_invested", 0)
        pnl_pct  = (pnl_pts / pts_in * 100) if pts_in else 0
        cur_val  = p.get("current_value") or pts_in

        lines.append(
            f"{p['ticker']:<7} | {pts_in:6.1f} | {cur_val:9.1f} | "
            f"{pnl_pct:+6.1f}% | {days_held:4d} | —"
        )
    return "\n".join(lines)


def _build_candidates_table(candidates: list[dict], held_tickers: set[str]) -> str:
    lines = ["Ticker  | Val Score | Signal    | P/E   | EV/EBITDA | Thesis snippet",
             "--------|-----------|-----------|-------|-----------|---------------"]
    for c in candidates[:25]:
        ticker = c.get("ticker", "")
        held_marker = " [HELD]" if ticker in held_tickers else ""
        thesis = (c.get("thesis") or "")[:60].replace("\n", " ")
        lines.append(
            f"{ticker:<7}{held_marker} | "
            f"{c.get('value_score') or 0:9.1f} | "
            f"{c.get('valuation_signal') or 'Fair':<9} | "
            f"{c.get('pe_ratio') or 0:5.1f} | "
            f"{c.get('ev_ebitda') or 0:9.1f} | "
            f"{thesis}"
        )
    return "\n".join(lines)


def _call_claude(prompt: str, client: anthropic.Anthropic) -> dict:
    message = client.messages.create(
        model=PORTFOLIO_MODEL,
        max_tokens=MAX_TOKENS,
        system="You are a disciplined portfolio manager. Output valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def _validate_decisions(llm_out: dict, positions: list[dict], cash: float) -> dict:
    """Sanitize LLM output: enforce point limits, cash check, no double-buys."""
    held_tickers = {p["ticker"] for p in positions}
    sell_tickers = {s["ticker"] for s in llm_out.get("sells", [])}
    after_sell_tickers = held_tickers - sell_tickers

    validated_buys = []
    remaining_cash = cash

    for buy in llm_out.get("buys", []):
        ticker = buy.get("ticker")
        points = float(buy.get("points", 0))

        if ticker in after_sell_tickers:
            logger.warning(f"[PortfolioMgr] Skip buy {ticker} — already held")
            continue
        if ticker in {b["ticker"] for b in validated_buys}:
            logger.warning(f"[PortfolioMgr] Skip duplicate buy {ticker}")
            continue
        if points < MIN_POINTS_PER_POSITION:
            points = MIN_POINTS_PER_POSITION
        if points > MAX_POINTS_PER_POSITION:
            points = MAX_POINTS_PER_POSITION
        if points > remaining_cash:
            logger.warning(f"[PortfolioMgr] Not enough cash for {ticker} ({points:.1f} pts needed)")
            break

        buy["points"] = round(points, 2)
        validated_buys.append(buy)
        after_sell_tickers.add(ticker)
        remaining_cash -= points

        if len(after_sell_tickers) >= MAX_POSITIONS:
            logger.info("[PortfolioMgr] Hit max 20 positions — stopping buys")
            break

    llm_out["buys"] = validated_buys
    return llm_out


def execute_sells(sells: list[dict], positions: list[dict]) -> float:
    """Execute all sell orders. Returns total cash reclaimed."""
    from data.database import get_cash_balance, insert_transaction, remove_position

    pos_map = {p["ticker"]: p for p in positions}
    total_reclaimed = 0.0
    today_str = date.today().isoformat()

    for sell in sells:
        ticker = sell["ticker"]
        if ticker not in pos_map:
            logger.warning(f"[PortfolioMgr] Sell {ticker} not in portfolio — skip")
            continue

        pos = pos_map[ticker]
        sell_price   = pos.get("current_price") or pos["buy_price"]
        sell_value   = round(pos["shares"] * sell_price, 4)
        realized_pnl = round(sell_value - pos["points_invested"], 4)

        insert_transaction({
            "date":      today_str,
            "ticker":    ticker,
            "action":    "SELL",
            "points":    sell_value,
            "price":     sell_price,
            "shares":    pos["shares"],
            "reasoning": sell.get("reasoning", ""),
            "pnl":       realized_pnl,
        })
        remove_position(ticker)
        total_reclaimed += sell_value

        logger.info(f"[PortfolioMgr] SOLD {ticker}: {sell_value:.1f} pts "
                    f"(P&L {realized_pnl:+.1f})")

    return total_reclaimed


def execute_buys(buys: list[dict], candidate_map: dict) -> None:
    """Execute all buy orders."""
    from data.database import insert_transaction, upsert_position

    today_str = date.today().isoformat()

    for buy in buys:
        ticker = buy["ticker"]
        points = buy["points"]

        # Get price: from screener candidate or live quote
        candidate = candidate_map.get(ticker, {})
        price = candidate.get("price") or _get_current_price(ticker)
        if not price:
            logger.warning(f"[PortfolioMgr] No price for {ticker} — skip buy")
            continue

        shares = round(points / price, 6)

        upsert_position({
            "ticker":          ticker,
            "company_name":    candidate.get("company_name", ticker),
            "points_invested": round(points, 4),
            "buy_price":       price,
            "shares":          shares,
            "buy_date":        today_str,
            "current_price":   price,
            "current_value":   round(points, 4),
            "unrealized_pnl":  0.0,
        })

        insert_transaction({
            "date":      today_str,
            "ticker":    ticker,
            "action":    "BUY",
            "points":    round(points, 4),
            "price":     price,
            "shares":    shares,
            "reasoning": buy.get("reasoning", ""),
            "pnl":       None,
        })

        logger.info(f"[PortfolioMgr] BOUGHT {ticker}: {points:.1f} pts @ ${price:.2f} "
                    f"({shares:.4f} shares)")
        time.sleep(0.3)


def run_portfolio_manager(screener_candidates: list[dict]) -> dict:
    """
    Main entry point. Reviews portfolio, calls Claude, executes decisions.
    Returns summary dict with {sells, buys, commentary, total_value, cash}.
    """
    from data.database import (
        get_cash_balance, get_portfolio, insert_portfolio_snapshot,
    )

    today_str = date.today().isoformat()
    logger.info("[PortfolioMgr] Starting daily portfolio review")

    # Step 1: Load current positions and refresh prices
    positions = get_portfolio()
    logger.info(f"[PortfolioMgr] {len(positions)} open positions")
    if positions:
        positions = refresh_prices(positions)

    # Step 2: Compute portfolio state
    cash = get_cash_balance()
    invested_value = sum(p.get("current_value") or p["points_invested"] for p in positions)
    total_value    = round(cash + invested_value, 2)
    total_pnl_pct  = round((total_value - 1000) / 1000 * 100, 2)

    logger.info(f"[PortfolioMgr] Total: {total_value:.1f} pts | "
                f"Cash: {cash:.1f} | Invested: {invested_value:.1f} | "
                f"P&L: {total_pnl_pct:+.2f}%")

    # Step 3: Build and fill prompt
    held_tickers = {p["ticker"] for p in positions}
    candidate_map = {c["ticker"]: c for c in screener_candidates}

    substitutions = {
        "{date}":            today_str,
        "{cash_available}":  f"{cash:.1f}",
        "{total_value}":     f"{total_value:.1f}",
        "{total_pnl_pct}":   f"{total_pnl_pct:+.2f}",
        "{positions_count}": str(len(positions)),
        "{positions_table}": _build_positions_table(positions),
        "{candidates_table}":_build_candidates_table(screener_candidates, held_tickers),
    }
    prompt = _load_prompt_template()
    for token, value in substitutions.items():
        prompt = prompt.replace(token, str(value))

    # Step 4: Call Claude
    client = _get_client()
    try:
        llm_out = _call_claude(prompt, client)
        logger.info(f"[PortfolioMgr] Claude decided: "
                    f"{len(llm_out.get('sells', []))} sells, "
                    f"{len(llm_out.get('buys', []))} buys")
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"[PortfolioMgr] Claude call failed: {e}")
        llm_out = {"sells": [], "buys": [], "portfolio_commentary": f"Error: {e}"}

    # Step 5: Validate and execute
    llm_out = _validate_decisions(llm_out, positions, cash)
    execute_sells(llm_out.get("sells", []), positions)
    execute_buys(llm_out.get("buys", []), candidate_map)

    # Step 6: Recompute after trades and snapshot
    positions_after = get_portfolio()
    cash_after      = get_cash_balance()
    invested_after  = sum(p.get("current_value") or p["points_invested"] for p in positions_after)
    total_after     = round(cash_after + invested_after, 2)
    total_pnl_after = round(total_after - 1000, 2)

    insert_portfolio_snapshot({
        "date":            today_str,
        "total_value":     total_after,
        "cash_balance":    round(cash_after, 2),
        "invested_value":  round(invested_after, 2),
        "daily_pnl":       round(total_after - total_value, 2),
        "total_pnl":       total_pnl_after,
        "positions_count": len(positions_after),
    })

    logger.info(f"[PortfolioMgr] Done. Portfolio: {total_after:.1f} pts, "
                f"{len(positions_after)} positions")

    return {
        "sells":       llm_out.get("sells", []),
        "buys":        llm_out.get("buys", []),
        "commentary":  llm_out.get("portfolio_commentary", ""),
        "total_value": total_after,
        "cash":        round(cash_after, 2),
        "positions":   len(positions_after),
    }
