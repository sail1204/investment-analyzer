"""
SQLite schema creation and CRUD helpers for the investment analyzer.
"""

import sqlite3
import json
import os
from datetime import datetime, date
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "memory/investment_analyzer.db")


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

            CREATE TABLE IF NOT EXISTS learning_state (
                state_type       TEXT NOT NULL,
                state_key        TEXT NOT NULL,
                value_json       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                PRIMARY KEY (state_type, state_key)
            );

            CREATE TABLE IF NOT EXISTS prompt_hints (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name      TEXT NOT NULL,
                scope_type      TEXT NOT NULL,
                scope_key       TEXT NOT NULL,
                hint_text       TEXT NOT NULL,
                strength        REAL DEFAULT 1.0,
                updated_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_learning_state_type_key
                ON learning_state(state_type, state_key);
            CREATE INDEX IF NOT EXISTS idx_prompt_hints_agent_scope
                ON prompt_hints(agent_name, scope_type, scope_key);

            CREATE TABLE IF NOT EXISTS learning_state_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date         TEXT NOT NULL,
                state_type       TEXT NOT NULL,
                state_key        TEXT NOT NULL,
                value_json       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prompt_hint_history (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date         TEXT NOT NULL,
                agent_name       TEXT NOT NULL,
                scope_type       TEXT NOT NULL,
                scope_key        TEXT NOT NULL,
                hint_text        TEXT NOT NULL,
                strength         REAL DEFAULT 1.0,
                updated_at       TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_learning_state_history_run
                ON learning_state_history(run_date, state_type, state_key);
            CREATE INDEX IF NOT EXISTS idx_prompt_hint_history_run
                ON prompt_hint_history(run_date, agent_name, scope_type, scope_key);

            -- ── Paper trading tables ──────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker          TEXT PRIMARY KEY,
                company_name    TEXT,
                points_invested REAL NOT NULL,
                buy_price       REAL NOT NULL,
                shares          REAL NOT NULL,
                buy_date        TEXT NOT NULL,
                thesis_run_date TEXT,
                thesis          TEXT,
                thesis_conviction INTEGER,
                thesis_signal   TEXT,
                thesis_catalyst TEXT,
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
                thesis_run_date TEXT,
                thesis    TEXT,
                thesis_conviction INTEGER,
                thesis_signal TEXT,
                thesis_catalyst TEXT,
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
        _ensure_column(conn, "portfolio", "thesis_run_date", "TEXT")
        _ensure_column(conn, "portfolio", "thesis", "TEXT")
        _ensure_column(conn, "portfolio", "thesis_conviction", "INTEGER")
        _ensure_column(conn, "portfolio", "thesis_signal", "TEXT")
        _ensure_column(conn, "portfolio", "thesis_catalyst", "TEXT")
        _ensure_column(conn, "transactions", "thesis_run_date", "TEXT")
        _ensure_column(conn, "transactions", "thesis", "TEXT")
        _ensure_column(conn, "transactions", "thesis_conviction", "INTEGER")
        _ensure_column(conn, "transactions", "thesis_signal", "TEXT")
        _ensure_column(conn, "transactions", "thesis_catalyst", "TEXT")
    print(f"[DB] Initialized database at {DB_PATH}")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str):
    existing = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if column not in {row["name"] for row in existing}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def load_watchlist_from_json(json_path: str = "memory/watchlist.json"):
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


def get_learning_rows(limit: int = 200) -> list[dict]:
    """
    Return correction rows joined with current-run snapshot context.
    Used by the deterministic learning pass.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                c.run_date,
                c.ticker,
                c.drift_signal,
                c.error_type,
                c.agents_explanation,
                s.sector,
                s.value_score,
                s.quality_score,
                s.conviction,
                s.valuation_signal
            FROM correction_log c
            LEFT JOIN stock_snapshots s
              ON s.run_date = c.run_date AND s.ticker = c.ticker
            ORDER BY c.run_date DESC, c.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def replace_learning_state(rows: list[dict], run_date: str):
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute("DELETE FROM learning_state")
        for row in rows:
            conn.execute(
                """
                INSERT INTO learning_state (state_type, state_key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    row["state_type"],
                    row["state_key"],
                    json.dumps(row["value"]),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO learning_state_history (run_date, state_type, state_key, value_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_date,
                    row["state_type"],
                    row["state_key"],
                    json.dumps(row["value"]),
                    now,
                ),
            )


def replace_prompt_hints(rows: list[dict], run_date: str):
    now = datetime.utcnow().isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.execute("DELETE FROM prompt_hints")
        for row in rows:
            conn.execute(
                """
                INSERT INTO prompt_hints (agent_name, scope_type, scope_key, hint_text, strength, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["agent_name"],
                    row["scope_type"],
                    row["scope_key"],
                    row["hint_text"],
                    row.get("strength", 1.0),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO prompt_hint_history (run_date, agent_name, scope_type, scope_key, hint_text, strength, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_date,
                    row["agent_name"],
                    row["scope_type"],
                    row["scope_key"],
                    row["hint_text"],
                    row.get("strength", 1.0),
                    now,
                ),
            )


def get_learning_state(state_type: str, state_key: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value_json FROM learning_state WHERE state_type = ? AND state_key = ?",
            (state_type, state_key),
        ).fetchone()
    return json.loads(row["value_json"]) if row else None


def get_prompt_hints(agent_name: str, scope_pairs: list[tuple[str, str]], limit: int = 6) -> list[dict]:
    if not scope_pairs:
        return []
    placeholders = " OR ".join(["(scope_type = ? AND scope_key = ?)"] * len(scope_pairs))
    params: list = [agent_name]
    for scope_type, scope_key in scope_pairs:
        params.extend([scope_type, scope_key])
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT agent_name, scope_type, scope_key, hint_text, strength, updated_at
            FROM prompt_hints
            WHERE agent_name = ? AND ({placeholders})
            ORDER BY strength DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_learning_state() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT state_type, state_key, value_json, updated_at
            FROM learning_state
            ORDER BY state_type, state_key
            """
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["value"] = json.loads(item.pop("value_json"))
        result.append(item)
    return result


def get_all_prompt_hints(limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT agent_name, scope_type, scope_key, hint_text, strength, updated_at
            FROM prompt_hints
            ORDER BY agent_name, strength DESC, updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_learning_state_history(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT run_date, state_type, state_key, value_json, updated_at
            FROM learning_state_history
            ORDER BY run_date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["value"] = json.loads(item.pop("value_json"))
        result.append(item)
    return result


def get_prompt_hint_history(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT run_date, agent_name, scope_type, scope_key, hint_text, strength, updated_at
            FROM prompt_hint_history
            ORDER BY run_date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
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


def get_trade_attribution(limit: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                sell.id AS sell_tx_id,
                sell.date AS sell_date,
                sell.ticker,
                sell.points AS sell_points,
                sell.price AS sell_price,
                sell.pnl AS realized_pnl,
                buy.id AS buy_tx_id,
                buy.date AS buy_date,
                buy.points AS buy_points,
                buy.price AS buy_price,
                buy.thesis_run_date,
                buy.thesis,
                buy.thesis_conviction,
                buy.thesis_signal,
                buy.thesis_catalyst
            FROM transactions sell
            LEFT JOIN transactions buy
              ON buy.id = (
                SELECT b.id
                FROM transactions b
                WHERE b.ticker = sell.ticker
                  AND b.action = 'BUY'
                  AND b.id < sell.id
                ORDER BY b.id DESC
                LIMIT 1
              )
            WHERE sell.action = 'SELL'
            ORDER BY sell.id DESC
            LIMIT ?
            """,
            (limit,),
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
