"""SQLite database access layer for the trading system."""

from __future__ import annotations

import sqlite3
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _default_db_path() -> str:
    """Pick a sensible default DB path. Honors TRADING_DB_PATH override.

    Outside containers we anchor on the repo root (parent of lib/). In Modal
    we anchor on /app (the working dir set by `os.chdir("/app")`) so the data
    dir lives under the writable /app tree rather than relative to the
    site-packages-style lib mount."""
    override = os.environ.get("TRADING_DB_PATH")
    if override:
        return override
    if os.path.isdir("/app/lib"):
        return "/app/data/db/trading.db"
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "db", "trading.db")


DB_PATH = _default_db_path()

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
    initial_sl REAL,
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
    resolved_at TEXT,
    -- How the bet was sourced. NOT NULL after backfill in lib.db.migrate_polymarket_discovery_method().
    -- Values: wallet_cluster_strong | wallet_cluster_weak | wallet_single |
    -- news_driven_researched | cross_market_arb | heuristic_paper
    discovery_method TEXT,
    discovery_evidence TEXT  -- JSON: wallets, citations, news urgency, etc.
);

-- Portfolio-level risk snapshots (Workstream 4). 15-min cadence from portfolio_risk_runner.
CREATE TABLE IF NOT EXISTS portfolio_risk_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_at TEXT NOT NULL DEFAULT (datetime('now')),
    capital_usd REAL,
    open_position_count INTEGER,
    gross_exposure_usd REAL,
    net_exposure_usd REAL,
    var_95_1d_usd REAL,
    cvar_95_1d_usd REAL,
    var_95_pct REAL,
    avg_pairwise_correlation REAL,
    max_pairwise_correlation REAL,
    factor_exposures_json TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_risk_snap_at ON portfolio_risk_snapshots(snapshot_at);

-- Daily correlation matrix across open positions.
CREATE TABLE IF NOT EXISTS correlation_matrix_daily (
    date TEXT NOT NULL,
    asset_a TEXT NOT NULL,
    asset_b TEXT NOT NULL,
    correlation REAL NOT NULL,
    window_days INTEGER NOT NULL,
    PRIMARY KEY (date, asset_a, asset_b)
);

-- Multi-agent brain action log (Workstream 1). One row per LLM call so we
-- can audit decisions, agreement rates, latency, and cost per agent.
CREATE TABLE IF NOT EXISTS agent_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    job TEXT NOT NULL,
    model TEXT NOT NULL,
    tier TEXT,
    payload_json TEXT,
    ok INTEGER NOT NULL DEFAULT 1,
    usd_cost REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_agent_actions_job ON agent_actions(job);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts  ON agent_actions(timestamp);

-- Semantic memory: lessons + rules the brain has accumulated. Embedded for RAG
-- once lib.rag_retrieval lands; for Stage 2 it's a plain text store.
CREATE TABLE IF NOT EXISTS agent_memory_semantic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    category TEXT NOT NULL,         -- 'lesson', 'rule', 'observation'
    subject TEXT,                   -- e.g. 'fomc-mean-reversion', 'pm-extreme-tail'
    body TEXT NOT NULL,
    confidence REAL DEFAULT 0.7,
    source_job TEXT,                -- which agent emitted this
    superseded_by INTEGER REFERENCES agent_memory_semantic(id)
);
CREATE INDEX IF NOT EXISTS idx_agent_mem_subject ON agent_memory_semantic(subject);

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

-- Strategy registry: canonical list of every strategy known to the system
CREATE TABLE IF NOT EXISTS strategy_registry (
    id TEXT PRIMARY KEY,              -- unique slug, e.g. "freqtrade.bbrsi_v1"
    name TEXT NOT NULL,
    description TEXT,
    source TEXT,                      -- e.g. "freqtrade", "jesse", "internal"
    source_url TEXT,
    source_commit TEXT,
    license TEXT,
    version TEXT,
    class_path TEXT,                  -- "lib.strategy_library.freqtrade.bbrsi_v1.BBRSIv1"
    timeframes_json TEXT,             -- JSON list of supported timeframes
    asset_classes_json TEXT,          -- JSON list: "crypto_perp", "crypto_spot", "forex"
    mode TEXT NOT NULL CHECK (mode IN ('backtest', 'paper', 'live', 'disabled')) DEFAULT 'backtest',
    params_json TEXT,                 -- current parameter values
    safe_bounds_json TEXT,            -- allowed ranges for auto-tuning
    backtest_snapshot_json TEXT,      -- latest qualifying backtest metrics
    paper_snapshot_json TEXT,         -- latest paper-mode metrics
    risk_notes TEXT,
    mode_changed_at TEXT,
    demotion_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Rolling performance per strategy (live + paper)
CREATE TABLE IF NOT EXISTS strategy_performance (
    strategy_id TEXT PRIMARY KEY REFERENCES strategy_registry(id),
    mode TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    total_pnl_usd REAL DEFAULT 0,
    avg_win_usd REAL,
    avg_loss_usd REAL,
    profit_factor REAL,
    expectancy_r REAL,
    win_rate REAL,
    last_20_win_rate REAL,
    sharpe_30d REAL,
    sortino_30d REAL,
    max_dd_pct REAL,
    consecutive_losses INTEGER DEFAULT 0,
    last_trade_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Backtest run history (a strategy can be backtested many times)
CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES strategy_registry(id),
    run_at TEXT NOT NULL DEFAULT (datetime('now')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    symbols_json TEXT,
    timeframe TEXT,
    starting_capital REAL,
    ending_capital REAL,
    trades INTEGER,
    win_rate REAL,
    profit_factor REAL,
    sharpe REAL,
    sortino REAL,
    max_dd_pct REAL,
    avg_r REAL,
    params_json TEXT,
    passed_gate INTEGER DEFAULT 0,
    notes TEXT
);

-- Partial closes: each scale-out tier executed against an open trade.
-- A single trade row may produce 3 TP tier rows + 1 runner row + 1 SL/time-stop row.
-- UNIQUE(trade_id, tier) prevents the same tier from firing twice.
CREATE TABLE IF NOT EXISTS partial_closes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id),
    tier INTEGER NOT NULL,
    tier_label TEXT,
    exit_price REAL NOT NULL,
    quantity_closed REAL NOT NULL,
    pnl_usd REAL NOT NULL,
    closed_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(trade_id, tier)
);
CREATE INDEX IF NOT EXISTS idx_partial_closes_trade ON partial_closes(trade_id);

-- Strategy hypotheses proposed by the self-improvement loop
CREATE TABLE IF NOT EXISTS strategy_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_at TEXT NOT NULL DEFAULT (datetime('now')),
    hypothesis_type TEXT NOT NULL CHECK (hypothesis_type IN ('param_tweak', 'new_variant', 'new_strategy')),
    parent_strategy_id TEXT REFERENCES strategy_registry(id),
    new_strategy_id TEXT REFERENCES strategy_registry(id),
    rationale TEXT,
    proposed_params_json TEXT,
    status TEXT CHECK (status IN ('pending_backtest', 'backtest_failed', 'in_paper', 'paper_failed', 'live', 'retired')) DEFAULT 'pending_backtest',
    resolved_at TEXT
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
CREATE INDEX IF NOT EXISTS idx_strategy_mode ON strategy_registry(mode);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON strategy_hypotheses(status);
"""


_SCHEMA_INIT_DONE: set[str] = set()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent column-level migrations for tables that pre-existed the new schema.

    SQLite's `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so
    columns we add to the SCHEMA literal must be ALTER-added separately for
    legacy DBs. Each migration is wrapped in try/except since a fresh DB will
    already have the column from the SCHEMA run above.
    """
    try:
        if not _column_exists(conn, "polymarket_bets", "discovery_method"):
            conn.execute("ALTER TABLE polymarket_bets ADD COLUMN discovery_method TEXT")
        if not _column_exists(conn, "polymarket_bets", "discovery_evidence"):
            conn.execute("ALTER TABLE polymarket_bets ADD COLUMN discovery_evidence TEXT")
        conn.commit()
    except sqlite3.Error:
        pass
    _seed_polymarket_strategies(conn)


_PM_STRATEGIES = [
    {
        "id": "polymarket-smart-money",
        "name": "Polymarket Smart Money Copy",
        "description": "Copy curated whale wallets with multi-signal confluence (cluster, single sharp, high conviction).",
        "source": "internal",
        "asset_classes_json": '["polymarket_binary"]',
        "mode": "paper",
        "risk_notes": "Requires non-empty tracked_accounts. Quarter-Kelly sizing, min 5% edge.",
    },
    {
        "id": "polymarket-heuristic",
        "name": "Polymarket Heuristic (paper-only)",
        "description": "Confluence-driven paper bets without wallet evidence. NOT for live trading.",
        "source": "internal",
        "asset_classes_json": '["polymarket_binary"]',
        "mode": "paper",
        "risk_notes": "Synthesized edges from confluence score only. Gated to confluence>=80 in execute path.",
    },
]


def _seed_polymarket_strategies(conn: sqlite3.Connection) -> None:
    """Seed strategy_registry rows for PM strategies so trades.strategy FKs resolve."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        for s in _PM_STRATEGIES:
            existing = conn.execute(
                "SELECT id FROM strategy_registry WHERE id=?", (s["id"],)
            ).fetchone()
            if existing:
                continue
            cols = list(s.keys()) + ["created_at", "updated_at", "mode_changed_at"]
            vals = list(s.values()) + [now, now, now]
            placeholders = ", ".join(["?"] * len(cols))
            conn.execute(
                f"INSERT INTO strategy_registry ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
        conn.commit()
    except sqlite3.Error:
        pass


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory enabled.

    Self-initializes the schema on first call per `db_path` so callers in
    fresh containers (e.g. Modal) don't have to remember to call init_db().
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if db_path not in _SCHEMA_INIT_DONE:
        try:
            conn.executescript(SCHEMA)
            conn.commit()
            _run_migrations(conn)
            _SCHEMA_INIT_DONE.add(db_path)
        except sqlite3.Error:
            # Don't crash the connection if schema setup races; the table-not-
            # found error from a follow-up query will surface the real issue.
            pass
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


def get_open_polymarket_trades(conn: sqlite3.Connection) -> list[dict]:
    """Return open Polymarket trades joined with polymarket_bets for market_id."""
    rows = conn.execute(
        """
        SELECT t.id        AS trade_id,
               t.asset     AS market_question,
               t.direction,
               t.entry_price,
               t.quantity,
               t.strategy,
               t.confluence_score,
               pb.market_id,
               pb.market_category
        FROM   trades t
        JOIN   polymarket_bets pb ON pb.trade_id = t.id
        WHERE  t.status = 'open'
          AND  t.pillar = 'polymarket'
        ORDER  BY t.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def log_partial_close(
    conn: sqlite3.Connection,
    trade_id: int,
    tier: int,
    tier_label: str,
    exit_price: float,
    quantity_closed: float,
    pnl_usd: float,
) -> int:
    """Record a partial scale-out against an open trade. Idempotent on (trade_id, tier)."""
    cursor = conn.execute(
        """INSERT OR IGNORE INTO partial_closes
           (trade_id, tier, tier_label, exit_price, quantity_closed, pnl_usd, closed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (trade_id, tier, tier_label, exit_price, quantity_closed, pnl_usd,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def get_partial_closes(conn: sqlite3.Connection, trade_id: int) -> list[dict]:
    """Return all partial closes for a trade, ordered by tier ascending."""
    rows = conn.execute(
        "SELECT * FROM partial_closes WHERE trade_id=? ORDER BY tier ASC",
        (trade_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_remaining_quantity(conn: sqlite3.Connection, trade_id: int, initial_qty: float) -> float:
    """Compute remaining open quantity = initial - sum(partial_closes.quantity_closed)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity_closed), 0) FROM partial_closes WHERE trade_id=?",
        (trade_id,),
    ).fetchone()
    closed = float(row[0] or 0)
    return max(0.0, initial_qty - closed)


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


def upsert_strategy(conn: sqlite3.Connection, strategy_id: str, **fields) -> None:
    """Insert or update a strategy in the registry. Unset fields are preserved on update."""
    existing = conn.execute("SELECT id FROM strategy_registry WHERE id=?", (strategy_id,)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if existing is None:
        fields["id"] = strategy_id
        fields.setdefault("created_at", now)
        fields.setdefault("updated_at", now)
        fields.setdefault("mode_changed_at", now)
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["?"] * len(fields))
        conn.execute(
            f"INSERT INTO strategy_registry ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
    else:
        fields["updated_at"] = now
        set_clause = ", ".join(f"{k}=?" for k in fields.keys())
        conn.execute(
            f"UPDATE strategy_registry SET {set_clause} WHERE id=?",
            list(fields.values()) + [strategy_id],
        )
    conn.commit()


def get_strategy(conn: sqlite3.Connection, strategy_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM strategy_registry WHERE id=?", (strategy_id,)).fetchone()
    return dict(row) if row else None


def list_strategies(conn: sqlite3.Connection, mode: str = None) -> list[dict]:
    """List strategies, optionally filtered by mode."""
    if mode:
        rows = conn.execute("SELECT * FROM strategy_registry WHERE mode=?", (mode,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM strategy_registry").fetchall()
    return [dict(r) for r in rows]


def set_strategy_mode(conn: sqlite3.Connection, strategy_id: str, mode: str, reason: str = None) -> None:
    """Transition a strategy's mode; always stamps mode_changed_at."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE strategy_registry SET mode=?, mode_changed_at=?, demotion_reason=?, updated_at=? WHERE id=?",
        (mode, now, reason, now, strategy_id),
    )
    conn.commit()


def log_backtest(conn: sqlite3.Connection, **kwargs) -> int:
    """Record a backtest run. Returns the backtest ID."""
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join(["?"] * len(kwargs))
    cursor = conn.execute(
        f"INSERT INTO backtest_results ({columns}) VALUES ({placeholders})",
        list(kwargs.values()),
    )
    conn.commit()
    return cursor.lastrowid


def upsert_strategy_performance(conn: sqlite3.Connection, strategy_id: str, **fields) -> None:
    """Insert or update rolling performance metrics for a strategy."""
    existing = conn.execute(
        "SELECT strategy_id FROM strategy_performance WHERE strategy_id=?", (strategy_id,)
    ).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    fields["updated_at"] = now
    if existing is None:
        fields["strategy_id"] = strategy_id
        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["?"] * len(fields))
        conn.execute(
            f"INSERT INTO strategy_performance ({cols}) VALUES ({placeholders})",
            list(fields.values()),
        )
    else:
        set_clause = ", ".join(f"{k}=?" for k in fields.keys())
        conn.execute(
            f"UPDATE strategy_performance SET {set_clause} WHERE strategy_id=?",
            list(fields.values()) + [strategy_id],
        )
    conn.commit()


def log_hypothesis(conn: sqlite3.Connection, **kwargs) -> int:
    """Record a strategy hypothesis proposed by the self-improvement loop."""
    columns = ", ".join(kwargs.keys())
    placeholders = ", ".join(["?"] * len(kwargs))
    cursor = conn.execute(
        f"INSERT INTO strategy_hypotheses ({columns}) VALUES ({placeholders})",
        list(kwargs.values()),
    )
    conn.commit()
    return cursor.lastrowid


if __name__ == "__main__":
    init_db()
