"""
Weekly orchestrator — runs all three agent steps in sequence:
  1. Screener  (quantitative filter → shortlist)
  2. Researcher (LLM thesis generation → snapshots)
  3. Self-Corrector (prior week diff → correction log)

Usage:
  python -m workflows.run_weekly              # run now
  python -m workflows.run_weekly --ticker AAPL
                                               # single-stock test run
  python -m workflows.run_weekly --dry-run    # screener only, no LLM calls
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run(tickers: list[str] | None = None, dry_run: bool = False, top_n: int = 8):
    """
    Main weekly run.

    Args:
        tickers: if set, restrict to these tickers only (for testing)
        dry_run: if True, skip LLM calls (screener only)
        top_n:   number of shortlisted candidates for deep research
    """
    from memory.database import (
        init_db, load_watchlist_from_json, get_active_watchlist,
        upsert_snapshot, insert_correction, current_run_date,
    )
    from logic.screener import run_screener
    from workflows.run_learning import run as run_learning
    from agent.researcher import run_researcher
    from agent.self_corrector import run_self_corrector

    # ── Setup ────────────────────────────────────────────────────────────────
    run_date = current_run_date()
    logger.info(f"{'='*60}")
    logger.info(f"  Investment Analyzer — Weekly Run")
    logger.info(f"  Run date: {run_date}  ({date.today().isoformat()})")
    logger.info(f"{'='*60}")

    init_db()
    load_watchlist_from_json()

    watchlist = get_active_watchlist()
    if tickers:
        watchlist = [s for s in watchlist if s["ticker"] in tickers]
        logger.info(f"Filtered to {len(watchlist)} specified tickers: {tickers}")

    if not watchlist:
        logger.error("No stocks in watchlist. Exiting.")
        return

    # ── Step 1: Screener ─────────────────────────────────────────────────────
    logger.info(f"\n── STEP 1: SCREENER ({len(watchlist)} stocks) ──")
    candidates = run_screener(watchlist, top_n=top_n if not tickers else len(tickers))

    logger.info(f"\nTop {len(candidates)} candidates:")
    logger.info(f"{'Rank':<5} {'Ticker':<7} {'Sector':<28} {'Composite':>9} {'Value':>6} {'Quality':>8} {'P/E':>6}")
    logger.info("-" * 72)
    for i, c in enumerate(candidates, 1):
        logger.info(
            f"{i:<5} {c['ticker']:<7} {c['sector'][:27]:<28} "
            f"{c['composite_score']:>9.1f} {c['value_score']:>6.1f} "
            f"{c['quality_score']:>8.1f} {str(c['pe_ratio'] or 'N/A'):>6}"
        )

    if dry_run:
        logger.info("\n[DRY RUN] Skipping researcher and self-corrector. Done.")
        return

    # ── Step 2: Researcher ───────────────────────────────────────────────────
    logger.info(f"\n── STEP 2: RESEARCHER ({len(candidates)} candidates) ──")
    snapshots = run_researcher(candidates, run_date)

    # Persist snapshots
    for snapshot in snapshots:
        upsert_snapshot(snapshot)
    logger.info(f"Saved {len(snapshots)} snapshots to DB.")

    # ── Step 3: Self-Corrector ───────────────────────────────────────────────
    logger.info(f"\n── STEP 3: SELF-CORRECTOR ──")
    corrections = run_self_corrector(snapshots, run_date)

    # Update snapshots with corrected thesis/conviction/price_change_1w
    for snapshot in snapshots:
        upsert_snapshot(snapshot)

    # Persist corrections
    for correction in corrections:
        insert_correction(correction)
    logger.info(f"Saved {len(corrections)} corrections to DB.")

    # ── Step 4: Learning pass ───────────────────────────────────────────────
    logger.info(f"\n── STEP 4: LEARNING ──")
    learning_result = run_learning(run_date=run_date)

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"  Run complete: {run_date}")
    logger.info(f"  Stocks screened:   {len(watchlist)}")
    logger.info(f"  Snapshots saved:   {len(snapshots)}")
    logger.info(f"  Corrections logged: {len(corrections)}")
    logger.info(f"  Learning states:   {learning_result.get('learning_state_rows', 0)}")
    logger.info(f"  Prompt hints:      {learning_result.get('prompt_hints', 0)}")

    if corrections:
        from collections import Counter
        drift_counts = Counter(c["drift_signal"] for c in corrections)
        logger.info(f"  Thesis drift: {dict(drift_counts)}")

    logger.info(f"{'='*60}\n")
    logger.info("Dashboard: python -m workflows.dashboard.server")


def schedule_weekly():
    """Run on a weekly schedule using APScheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    # Run every Monday at 06:00 local time
    scheduler.add_job(
        run,
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="weekly_run",
        name="Investment Analyzer Weekly Run",
        replace_existing=True,
    )
    logger.info("Scheduler started. Next run: Monday 06:00.")
    logger.info("Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Investment Analyzer — Weekly Run")
    parser.add_argument(
        "--ticker", nargs="+", metavar="TICKER",
        help="Run for specific tickers only (e.g. --ticker AAPL MSFT)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run screener only — no LLM calls"
    )
    parser.add_argument(
        "--top-n", type=int, default=8,
        help="Number of top candidates to research (default: 8)"
    )
    parser.add_argument(
        "--schedule", action="store_true",
        help="Run on a weekly schedule (every Monday 06:00)"
    )
    args = parser.parse_args()

    if args.schedule:
        schedule_weekly()
    else:
        run(
            tickers=args.ticker,
            dry_run=args.dry_run,
            top_n=args.top_n,
        )
