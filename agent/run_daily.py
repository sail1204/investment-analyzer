"""
Daily orchestrator — runs the paper trading pipeline:
  1. Screener  (quantitative filter → top-N candidates)
  2. Researcher (LLM thesis, only for stocks NOT currently held)
  3. Portfolio Manager (Claude buy/sell decisions)

Usage:
  python -m agent.run_daily                # run now (full run)
  python -m agent.run_daily --dry-run      # screener only, no trades, no LLM
  python -m agent.run_daily --force        # ignore weekday check, run now
  python -m agent.run_daily --schedule     # start APScheduler (weekdays, noon)
  python -m agent.run_daily --top-n 25     # override screener candidate count
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run(dry_run: bool = False, top_n: int = 20):
    """
    Full daily run: screener → researcher (non-held only) → portfolio manager.

    Args:
        dry_run: if True, run screener only — no LLM calls, no trades
        top_n:   number of screener candidates to pass to the portfolio manager
    """
    from data.database import (
        init_db, load_watchlist_from_json, get_active_watchlist,
        get_portfolio, upsert_snapshot,
    )
    from agent.screener import run_screener
    from agent.researcher import run_researcher
    from agent.portfolio_manager import run_portfolio_manager

    today_str = date.today().isoformat()

    logger.info("=" * 60)
    logger.info("  Investment Analyzer — Daily Run")
    logger.info(f"  Date: {today_str}")
    logger.info("=" * 60)

    # ── Setup ────────────────────────────────────────────────────────────────
    init_db()
    load_watchlist_from_json()

    watchlist = get_active_watchlist()
    if not watchlist:
        logger.error("No stocks in watchlist. Exiting.")
        return

    # ── Step 1: Screener ─────────────────────────────────────────────────────
    logger.info(f"\n── STEP 1: SCREENER ({len(watchlist)} stocks) ──")
    candidates = run_screener(watchlist, top_n=top_n)

    logger.info(f"\nTop {len(candidates)} candidates:")
    logger.info(
        f"{'Rank':<5} {'Ticker':<7} {'Sector':<28} "
        f"{'Composite':>9} {'Value':>6} {'Quality':>8} {'P/E':>6}"
    )
    logger.info("-" * 72)
    for i, c in enumerate(candidates, 1):
        logger.info(
            f"{i:<5} {c['ticker']:<7} {c['sector'][:27]:<28} "
            f"{c['composite_score']:>9.1f} {c['value_score']:>6.1f} "
            f"{c['quality_score']:>8.1f} {str(c['pe_ratio'] or 'N/A'):>6}"
        )

    if dry_run:
        logger.info("\n[DRY RUN] Stopping after screener. No LLM calls, no trades.")
        return

    # ── Step 2: Researcher (non-held tickers only) ───────────────────────────
    held_tickers = {p["ticker"] for p in get_portfolio()}
    logger.info(f"\n── STEP 2: RESEARCHER ──")
    logger.info(f"Currently held: {sorted(held_tickers) or '(none)'}")

    # Research candidates not already in portfolio (up to 10 at a time to limit API cost)
    to_research = [c for c in candidates if c["ticker"] not in held_tickers][:10]

    if to_research:
        # Use today's date as the run_date key for daily snapshots
        # We reuse the weekly run_date format for compatibility with the dashboard
        from data.database import current_run_date
        run_date = current_run_date()

        snapshots = run_researcher(to_research, run_date)
        for snapshot in snapshots:
            upsert_snapshot(snapshot)
        logger.info(f"Saved {len(snapshots)} new snapshots to DB.")
    else:
        logger.info("All top candidates already held — skipping researcher.")

    # ── Step 3: Portfolio Manager ────────────────────────────────────────────
    logger.info(f"\n── STEP 3: PORTFOLIO MANAGER ──")
    result = run_portfolio_manager(candidates)

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("  Daily Run Complete")
    logger.info(f"  Date:          {today_str}")
    logger.info(f"  Sells:         {len(result.get('sells', []))}")
    logger.info(f"  Buys:          {len(result.get('buys', []))}")
    logger.info(f"  Positions:     {result.get('positions', 0)}")
    logger.info(f"  Total Value:   {result.get('total_value', 0):.1f} pts")
    logger.info(f"  Cash:          {result.get('cash', 0):.1f} pts")
    commentary = result.get("commentary", "")
    if commentary:
        logger.info(f"\n  Commentary: {commentary}")
    logger.info("=" * 60 + "\n")
    logger.info("Dashboard: python -m dashboard.server")

    return result


def _is_weekday() -> bool:
    return date.today().weekday() < 5   # 0=Mon … 4=Fri


def schedule_daily():
    """Run on a daily schedule using APScheduler (weekdays only, noon in SCHEDULER_TZ)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    tz_name = os.getenv("SCHEDULER_TZ", "UTC")
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{tz_name}', falling back to UTC")
        tz = pytz.utc

    def _guarded_run():
        from datetime import datetime
        now = datetime.now(tz)
        if now.weekday() >= 5:
            logger.info("[Scheduler] Weekend — skipping run.")
            return
        run()

    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        _guarded_run,
        trigger=CronTrigger(hour=12, minute=0, timezone=tz),
        id="daily_run",
        name="Investment Analyzer Daily Run",
        replace_existing=True,
    )
    logger.info(f"Scheduler started. Fires weekdays at 12:00 noon {tz_name}.")
    logger.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Investment Analyzer — Daily Run")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run screener only — no LLM calls, no trades",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Run immediately regardless of day of week",
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Start APScheduler (weekdays, 12:00 noon)",
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Number of screener candidates to use (default: 20)",
    )
    args = parser.parse_args()

    if args.schedule:
        schedule_daily()
    elif args.force or _is_weekday():
        run(dry_run=args.dry_run, top_n=args.top_n)
    else:
        logger.info("Today is a weekend. Use --force to run anyway.")
