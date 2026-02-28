"""
SQLite schema creation and CRUD helpers for the investment analyzer.
"""

import sqlite3
import json
import os
from datetime import datetime, date
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "data/investment_analyzer.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker              TEXT PRIMARY KEY,
                company_name        TEXT NOT NULL,
                sector              TEXT NOT NULL,
                gics_sub_industry   TEXT,
                active              INTEGER NOT NULL DEFAULT 1,
                added_date          TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_snapshots (
                run_date            TEXT NOT NULL,
                ticker              TEXT NOT NULL,
                company_name        TEXT,
                sector              TEXT,
                price               REAL,
                price_change_1w     REAL,
                pe_ratio            REAL,
                pb_ratio            REAL,
                ev_ebitda           REAL,
                roe                 REAL,
                fcf_yield           REAL,
                debt_equity         REAL,
                value_score         REAL,
                quality_score       REAL,
                conviction          INTEGER,
                valuation_signal    TEXT,
                thesis              TEXT,
                key_risk            TEXT,
                catalyst            TEXT,
                second_order_effects TEXT,
                thesis_age_weeks    INTEGER DEFAULT 1,
                PRIMARY KEY (run_date, ticker)
            );

            CREATE TABLE IF NOT EXISTS correction_log (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date                TEXT NOT NULL,
                ticker                  TEXT NOT NULL,
                prior_thesis            TEXT,
                what_happened           TEXT,
                agents_explanation      TEXT,
                drift_signal            TEXT,
                error_type              TEXT,
                was_directionally_correct INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_ticker
                ON stock_snapshots(ticker);
            CREATE INDEX IF NOT EXISTS idx_snapshots_run_date
                ON stock_snapshots(run_date);
            CREATE INDEX IF NOT EXISTS idx_corrections_ticker
                ON correction_log(ticker);

            -- ── Paper trading tables ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker          TEXT PRIMARY KEY,
                company_name    TEXT,
                points_invested REAL NOT NULL,
                buy_price       REAL NOT NULL,
                shares          REAL NOT NULL,
                buy_date        TEXT NOT NULL,
                current_price   REAL,
                current_value   REAL,
                unrealized_pnl  REAL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                ticker    TEXT NOT NULL,
                action    TEXT NOT NULL,
                points    REAL NOT NULL,
                price     REAL NOT NULL,
                shares    REAL NOT NULL,
                reasoning TEXT,
                pnl       REAL
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                date            TEXT PRIMARY KEY,
                total_value     REAL,
                cash_balance    REAL,
                invested_value  REAL,
                daily_pnl       REAL,
                total_pnl       REAL,
                positions_count INTEGER
            );
        """)
    print(f"[DB] Initialized database at {DB_PATH}")


def load_watchlist_from_json(json_path: str = "data/watchlist.json"):
    """Seed the watchlist table from watchlist.json (idempotent)."""
    with open(json_path) as f:
        data = json.load(f)

    today = date.today().isoformat()
    with get_connection() as conn:
        for stock in data["stocks"]:
            conn.execute("""
                INSERT OR IGNORE INTO watchlist
                    (ticker, company_name, sector, gics_sub_industry, active, added_date)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (
                stock["ticker"],
                stock["company_name"],
                stock["sector"],
                stock.get("gics_sub_industry"),
                today,
            ))
    print(f"[DB] Watchlist seeded with {len(data['stocks'])} stocks")


def get_active_watchlist() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE active = 1 ORDER BY sector, ticker"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_snapshot(snapshot: dict):
    """Insert or replace a stock snapshot for the given run_date + ticker."""
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO stock_snapshots (
                run_date, ticker, company_name, sector,
                price, price_change_1w,
                pe_ratio, pb_ratio, ev_ebitda, roe, fcf_yield, debt_equity,
                value_score, quality_score,
                conviction, valuation_signal,
                thesis, key_risk, catalyst, second_order_effects,
                thesis_age_weeks
            ) VALUES (
                :run_date, :ticker, :company_name, :sector,
                :price, :price_change_1w,
                :pe_ratio, :pb_ratio, :ev_ebitda, :roe, :fcf_yield, :debt_equity,
                :value_score, :quality_score,
                :conviction, :valuation_signal,
                :thesis, :key_risk, :catalyst, :second_order_effects,
                :thesis_age_weeks
            )
        """, snapshot)


def get_snapshot(ticker: str, run_date: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM stock_snapshots WHERE ticker = ? AND run_date = ?",
            (ticker, run_date),
        ).fetchone()
    return dict(row) if row else None


def get_latest_snapshot(ticker: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM stock_snapshots WHERE ticker = ? ORDER BY run_date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
    return dict(row) if row else None


def get_prior_snapshot(ticker: str, current_run_date: str) -> Optional[dict]:
    """Get the most recent snapshot before current_run_date."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT * FROM stock_snapshots
               WHERE ticker = ? AND run_date < ?
               ORDER BY run_date DESC LIMIT 1""",
            (ticker, current_run_date),
        ).fetchone()
    return dict(row) if row else None


def get_all_snapshots_for_run(run_date: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stock_snapshots WHERE run_date = ? ORDER BY value_score DESC",
            (run_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_ticker_history(ticker: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM stock_snapshots WHERE ticker = ? ORDER BY run_date ASC",
            (ticker,),
        ).fetchall()
    return [dict(r) for r in rows]


def insert_correction(correction: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO correction_log (
                run_date, ticker, prior_thesis, what_happened,
                agents_explanation, drift_signal, error_type, was_directionally_correct
            ) VALUES (
                :run_date, :ticker, :prior_thesis, :what_happened,
                :agents_explanation, :drift_signal, :error_type, :was_directionally_correct
            )
        """, correction)


def get_corrections_for_run(run_date: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM correction_log WHERE run_date = ? ORDER BY ticker",
            (run_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_corrections() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM correction_log ORDER BY run_date DESC, ticker"
        ).fetchall()
    return [dict(r) for r in rows]


def get_available_run_dates() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT run_date FROM stock_snapshots ORDER BY run_date DESC"
        ).fetchall()
    return [r["run_date"] for r in rows]


def current_run_date() -> str:
    """Returns 'YYYY-WW' — ISO year + week number."""
    today = date.today()
    iso = today.isocalendar()
    return f"{iso.year}-{iso.week:02d}"


# ── Portfolio / paper-trading helpers ─────────────────────────────────────────

STARTING_POINTS = 1000.0


def get_portfolio() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio ORDER BY points_invested DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_position(pos: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO portfolio
                (ticker, company_name, points_invested, buy_price, shares,
                 buy_date, current_price, current_value, unrealized_pnl)
            VALUES
                (:ticker, :company_name, :points_invested, :buy_price, :shares,
                 :buy_date, :current_price, :current_value, :unrealized_pnl)
        """, pos)


def remove_position(ticker: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM portfolio WHERE ticker = ?", (ticker,))


def insert_transaction(tx: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO transactions
                (date, ticker, action, points, price, shares, reasoning, pnl)
            VALUES
                (:date, :ticker, :action, :points, :price, :shares, :reasoning, :pnl)
        """, tx)


def get_transactions(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_cash_balance() -> float:
    """Compute remaining cash: 1000 − Σbuys + Σsell proceeds."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN action='BUY'  THEN points ELSE 0 END), 0) AS total_spent,
                COALESCE(SUM(CASE WHEN action='SELL' THEN points ELSE 0 END), 0) AS total_received
            FROM transactions
        """).fetchone()
    return STARTING_POINTS - row["total_spent"] + row["total_received"]


def insert_portfolio_snapshot(snap: dict):
    with get_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO portfolio_snapshots
                (date, total_value, cash_balance, invested_value,
                 daily_pnl, total_pnl, positions_count)
            VALUES
                (:date, :total_value, :cash_balance, :invested_value,
                 :daily_pnl, :total_pnl, :positions_count)
        """, snap)


def get_portfolio_history() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    load_watchlist_from_json()
    watchlist = get_active_watchlist()
    print(f"[DB] {len(watchlist)} active stocks in watchlist")
