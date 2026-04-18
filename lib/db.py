"""SQLite database access layer for the trading system."""

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "db", "trading.db")

SCHEMA = """
-- Trade journal: every trade ever placed
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    pillar TEXT NOT NULL CHECK (pillar IN ('market', 'polymarket')),
    asset TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short', 'yes', 'no')),
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity REAL NOT NULL,
    leverage REAL DEFAULT 1.0,
    stop_loss REAL,
    take_profit REAL,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'cancelled')) DEFAULT 'open',
    pnl_usd REAL,
    pnl_pct REAL,
    fees_usd REAL DEFAULT 0,
    strategy TEXT,
    confluence_score REAL,
    signals_json TEXT,
    reasoning TEXT,
    risk_check_result TEXT,
    opened_at TEXT,
    closed_at TEXT,
    broker TEXT
);

-- Signal history: every signal detected
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    signal_type TEXT NOT NULL,
    asset TEXT NOT NULL,
    direction TEXT,
    strength REAL,
    source TEXT,
    details_json TEXT,
    acted_on INTEGER DEFAULT 0
);

-- Daily P&L snapshots
CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    starting_capital REAL,
    ending_capital REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    max_drawdown_pct REAL,
    pillar_market_pnl REAL,
    pillar_polymarket_pnl REAL
);

-- Polymarket bets (extends trades with PM-specific fields)
CREATE TABLE IF NOT EXISTS polymarket_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER REFERENCES trades(id),
    market_id TEXT NOT NULL,
    market_question TEXT,
    market_category TEXT,
    estimated_probability REAL,
    market_odds REAL,
    edge_pct REAL,
    kelly_bet_size REAL,
    resolution TEXT,
    resolved_at TEXT
);

-- Followed accounts performance tracking
CREATE TABLE IF NOT EXISTS account_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    alias TEXT,
    check_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    win_rate REAL,
    total_trades INTEGER,
    pnl_30d REAL,
    skill_score REAL,
    signals_generated INTEGER DEFAULT 0,
    signals_profitable INTEGER DEFAULT 0
);

-- System state and circuit breakers
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Initialize system state
INSERT OR IGNORE INTO system_state (key, value) VALUES ('trading_halted', 'false');
INSERT OR IGNORE INTO system_state (key, value) VALUES ('consecutive_losses', '0');
INSERT OR IGNORE INTO system_state (key, value) VALUES ('daily_pnl_usd', '0');
INSERT OR IGNORE INTO system_state (key, value) VALUES ('weekly_pnl_usd', '0');
INSERT OR IGNORE INTO system_state (key, value) VALUES ('market_regime', 'unknown');

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_pillar ON trades(pillar);
CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset);
CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_asset ON signals(asset);
CREATE INDEX IF NOT EXISTS idx_account_perf_platform ON account_performance(platform);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize the database schema."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.close()
    print(f"Database initialized at {db_path}")


def log_trade(conn: sqlite3.Connection, **kwargs) -> int:
    """Insert a new trade record. Returns the trade ID."""
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join(["?"] * len(kwargs))
    cursor = conn.execute(
        f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
        list(kwargs.values()),
    )
    conn.commit()
    return cursor.lastrowid


def close_trade(conn: sqlite3.Connection, trade_id: int, exit_price: float, pnl_usd: float, pnl_pct: float, fees: float = 0) -> None:
    """Close an open trade with exit details."""
    conn.execute(
        """UPDATE trades SET status='closed', exit_price=?, pnl_usd=?, pnl_pct=?, fees_usd=?, closed_at=?
           WHERE id=?""",
        (exit_price, pnl_usd, pnl_pct, fees, datetime.now(timezone.utc).isoformat(), trade_id),
    )
    conn.commit()


def get_open_trades(conn: sqlite3.Connection, pillar: str = None) -> list[dict]:
    """Get all open trades, optionally filtered by pillar."""
    query = "SELECT * FROM trades WHERE status='open'"
    params = []
    if pillar:
        query += " AND pillar=?"
        params.append(pillar)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def log_signal(conn: sqlite3.Connection, **kwargs) -> int:
    """Insert a new signal record."""
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join(["?"] * len(kwargs))
    cursor = conn.execute(
        f"INSERT INTO signals ({columns}) VALUES ({placeholders})",
        list(kwargs.values()),
    )
    conn.commit()
    return cursor.lastrowid


def get_system_state(conn: sqlite3.Connection, key: str) -> str:
    """Get a system state value."""
    row = conn.execute("SELECT value FROM system_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_system_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Set a system state value."""
    conn.execute(
        "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_today_trades(conn: sqlite3.Connection) -> list[dict]:
    """Get all trades from today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM trades WHERE date(timestamp) = ?", (today,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_daily_stats(conn: sqlite3.Connection, date: str = None) -> dict:
    """Get aggregate stats for a given date (defaults to today)."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as winning,
            SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as losing,
            COALESCE(SUM(pnl_usd), 0) as total_pnl,
            COALESCE(MIN(pnl_usd), 0) as worst_trade,
            COALESCE(MAX(pnl_usd), 0) as best_trade
        FROM trades WHERE date(timestamp) = ? AND status='closed'""",
        (date,),
    ).fetchone()
    return dict(row) if row else {}


if __name__ == "__main__":
    init_db()
