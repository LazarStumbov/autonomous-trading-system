"""Unit tests for TP-tier partial-close logic in position_monitor.py.

Tests six scenarios against a temp SQLite DB (TRADING_DB_PATH env var).
Prices are injected by monkeypatching pm.get_public_price.
"""

from __future__ import annotations

import os
import sys
import tempfile
import importlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# ── Resolve project root ────────────────────────────────────────────────────
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── Shared fixtures ─────────────────────────────────────────────────────────

# Trade params reused across scenarios
ENTRY = 100.0
INITIAL_SL = 98.0
QTY = 10.0
RISK = ENTRY - INITIAL_SL  # 2.0

# TP tier prices (from config: r=1.0, 2.0, 3.5 for long trade)
TP1_PRICE = ENTRY + 1.0 * RISK   # 102.0
TP2_PRICE = ENTRY + 2.0 * RISK   # 104.0
TP3_PRICE = ENTRY + 3.5 * RISK   # 107.0


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Fresh SQLite DB per test. Sets TRADING_DB_PATH and patches lib.db.DB_PATH."""
    db_path = str(tmp_path / "test_trading.db")
    monkeypatch.setenv("TRADING_DB_PATH", db_path)

    # Re-import lib.db so DB_PATH picks up the env var
    import lib.db as db_mod
    # Force schema re-init (different path each test)
    db_mod._SCHEMA_INIT_DONE.discard(db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)

    conn = db_mod.get_connection(db_path)
    yield conn, db_path, db_mod
    conn.close()


def _insert_long_trade(db_mod, conn, opened_at: str | None = None) -> int:
    """Helper: insert a standard long paper trade and return its id."""
    now = opened_at or datetime.now(timezone.utc).isoformat()
    return db_mod.log_trade(
        conn,
        pillar="market",
        asset="BTC/USDT:USDT",
        direction="long",
        entry_price=ENTRY,
        quantity=QTY,
        stop_loss=INITIAL_SL,
        initial_sl=INITIAL_SL,
        status="open",
        broker="paper",
        opened_at=now,
        leverage=1.0,
    )


def _insert_short_trade(db_mod, conn) -> int:
    """Helper: insert a standard short paper trade and return its id."""
    now = datetime.now(timezone.utc).isoformat()
    return db_mod.log_trade(
        conn,
        pillar="market",
        asset="BTC/USDT:USDT",
        direction="short",
        entry_price=ENTRY,
        quantity=QTY,
        stop_loss=ENTRY + RISK,   # 102 — SL above entry for short
        initial_sl=ENTRY + RISK,
        status="open",
        broker="paper",
        opened_at=now,
        leverage=1.0,
    )


def _load_pm(monkeypatch, db_mod, fixed_price: float):
    """Import position_monitor fresh and patch get_public_price + get_exchange."""
    # Force fresh import so it re-reads the patched DB_PATH
    import lib.paper_engine as pe_mod
    monkeypatch.setattr(pe_mod, "get_public_price", lambda sym: fixed_price)

    if "position_monitor" in sys.modules:
        del sys.modules[
            ".claude.skills.execute-trade.scripts.position_monitor".replace(".", "/")
        ]
    # Remove cached module if present (different key due to path import)
    for key in list(sys.modules.keys()):
        if "position_monitor" in key:
            del sys.modules[key]

    spec_path = os.path.join(
        PROJECT_ROOT,
        ".claude", "skills", "execute-trade", "scripts", "position_monitor.py"
    )
    import importlib.util
    spec = importlib.util.spec_from_file_location("position_monitor", spec_path)
    pm = importlib.util.load_from_spec(spec) if False else None  # type: ignore
    pm = importlib.util.module_from_spec(spec)
    sys.modules["position_monitor"] = pm
    spec.loader.exec_module(pm)  # type: ignore

    # Patch get_public_price inside the loaded module
    monkeypatch.setattr(pm, "get_public_price", lambda sym: fixed_price)
    # Patch get_exchange to avoid broker import
    monkeypatch.setattr(pm, "get_exchange", lambda: None)
    # Patch paper mode to True so trade is treated as paper
    monkeypatch.setattr(pm, "is_paper_mode", lambda: True)
    # Patch credit_paper_balance to no-op to avoid secondary DB write
    monkeypatch.setattr(pm, "credit_paper_balance", lambda pnl, reason="": None)

    return pm


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 1 — Long trade: TP1 hits, then SL trips before TP2
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario1_long_tp1_then_sl(tmp_db, monkeypatch):
    """TP1 fires, SL (now at breakeven=entry) trips. Expect 2 partial_close rows."""
    conn, db_path, db_mod = tmp_db

    trade_id = _insert_long_trade(db_mod, conn)
    conn.close()  # position_monitor opens its own connection

    # Phase A: price at TP1 — should fire TP1 and move SL to breakeven
    pm = _load_pm(monkeypatch, db_mod, fixed_price=TP1_PRICE)
    result = pm.monitor_positions()
    assert result["status"] == "MONITORED"

    # Phase B: price drops back to entry (breakeven SL) — SL_HIT
    pm2 = _load_pm(monkeypatch, db_mod, fixed_price=ENTRY)
    result2 = pm2.monitor_positions()

    conn2 = db_mod.get_connection(db_path)
    partials = db_mod.get_partial_closes(conn2, trade_id)
    trade_row = conn2.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn2.close()

    labels = [p["tier_label"] for p in partials]
    assert len(partials) == 2, f"Expected 2 partial closes, got {len(partials)}: {labels}"
    assert "TP1" in labels, "TP1 partial close missing"
    assert "SL_HIT" in labels, "SL_HIT partial close missing"

    # TP1 tier is 1; SL_HIT is 99
    tier_map = {p["tier_label"]: p for p in partials}
    assert tier_map["TP1"]["tier"] == 1
    assert tier_map["SL_HIT"]["tier"] == 99

    # After TP1 the SL should move to breakeven (entry=100), so SL_HIT pnl ~ 0
    sl_hit_pnl = tier_map["SL_HIT"]["pnl_usd"]
    assert abs(sl_hit_pnl) < 0.01, f"SL_HIT pnl should be ~0 (breakeven SL), got {sl_hit_pnl}"

    # Trade should be closed
    assert trade_row["status"] == "closed", f"Trade not finalized: {dict(trade_row)}"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2 — Long trade: all 3 tiers + runner trailed out
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario2_all_tiers_then_runner(tmp_db, monkeypatch):
    """All 3 TP tiers fire sequentially, then runner exits via SL_HIT."""
    conn, db_path, db_mod = tmp_db
    trade_id = _insert_long_trade(db_mod, conn)
    conn.close()

    # TP1 at 102, TP2 at 104, TP3 at 107 — fire all in one sweep at 107+
    pm = _load_pm(monkeypatch, db_mod, fixed_price=TP3_PRICE)
    pm.monitor_positions()

    conn2 = db_mod.get_connection(db_path)
    partials_mid = db_mod.get_partial_closes(conn2, trade_id)
    conn2.close()

    tp_labels = {p["tier_label"] for p in partials_mid}
    assert "TP1" in tp_labels, "TP1 not fired"
    assert "TP2" in tp_labels, "TP2 not fired"
    assert "TP3" in tp_labels, "TP3 not fired"

    # Runner still open — check remaining qty
    conn3 = db_mod.get_connection(db_path)
    remaining = db_mod.get_remaining_quantity(conn3, trade_id, QTY)
    conn3.close()
    expected_remaining = QTY * (1 - (40 + 35 + 15) / 100)  # 10% runner = 1.0
    assert abs(remaining - expected_remaining) < 1e-9, (
        f"Expected runner qty={expected_remaining}, got {remaining}"
    )

    # Now drop price below trailing SL — simulate SL_HIT on runner
    # Trailing SL activates when pnl_pct >= 1.5%. At TP3=107, pnl_pct=7% > 3% threshold.
    # Trail distance 2% → trail_sl ≈ 107*(1-0.02) = 104.86
    # Inject price below the computed trailing SL by going to entry (definitely below trail)
    pm2 = _load_pm(monkeypatch, db_mod, fixed_price=ENTRY)
    pm2.monitor_positions()

    conn4 = db_mod.get_connection(db_path)
    partials_final = db_mod.get_partial_closes(conn4, trade_id)
    trade_row = conn4.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn4.close()

    labels_final = [p["tier_label"] for p in partials_final]
    assert "SL_HIT" in labels_final, f"SL_HIT not found in {labels_final}"
    assert len(partials_final) == 4, f"Expected 4 partial closes, got {len(partials_final)}"

    # Trade finalized
    assert trade_row["status"] == "closed"

    # Trade pnl = sum of all partials
    total_partial_pnl = sum(float(p["pnl_usd"]) for p in partials_final)
    assert abs(float(trade_row["pnl_usd"]) - total_partial_pnl) < 0.01, (
        f"Trade pnl {trade_row['pnl_usd']} != sum of partials {total_partial_pnl}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 3 — Short trade sign conventions
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario3_short_sign_conventions(tmp_db, monkeypatch):
    """Short trade: price move DOWN is profit. TP1 at entry-1R, SL above entry."""
    conn, db_path, db_mod = tmp_db
    trade_id = _insert_short_trade(db_mod, conn)
    conn.close()

    # For short: TP1 is at entry - 1*risk = 100 - 2 = 98
    short_tp1_price = ENTRY - 1.0 * RISK  # 98.0

    pm = _load_pm(monkeypatch, db_mod, fixed_price=short_tp1_price)
    pm.monitor_positions()

    conn2 = db_mod.get_connection(db_path)
    partials = db_mod.get_partial_closes(conn2, trade_id)
    conn2.close()

    assert len(partials) >= 1, f"Expected at least 1 partial close, got {len(partials)}"
    tp1 = next((p for p in partials if p["tier_label"] == "TP1"), None)
    assert tp1 is not None, "TP1 not logged for short trade"

    # Profit for short when price drops: pnl = (entry - current) * qty_closed
    qty_close = QTY * 0.40
    expected_pnl = (ENTRY - short_tp1_price) * qty_close  # (100-98)*4 = 8.0
    assert abs(float(tp1["pnl_usd"]) - expected_pnl) < 0.01, (
        f"Short TP1 pnl: expected {expected_pnl}, got {tp1['pnl_usd']}"
    )

    # After TP1 SL transitions to breakeven (entry=100 for short, SL moves to entry)
    # Confirm trade row still open (only TP1 fired)
    conn3 = db_mod.get_connection(db_path)
    trade_row = conn3.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn3.close()
    assert trade_row["status"] == "open", "Short trade should still be open after TP1"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 4 — Time-stop trigger
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario4_time_stop(tmp_db, monkeypatch):
    """Trade open for 9h with r_moved < 1.0 → TIME_STOP fires."""
    conn, db_path, db_mod = tmp_db

    # opened_at = 9 hours ago
    opened_at = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    trade_id = _insert_long_trade(db_mod, conn, opened_at=opened_at)
    conn.close()

    # Price barely above entry but below TP1 (r_moved < 1.0)
    stale_price = ENTRY + 0.5  # r = 0.25 < 1.0

    pm = _load_pm(monkeypatch, db_mod, fixed_price=stale_price)
    result = pm.monitor_positions()

    conn2 = db_mod.get_connection(db_path)
    partials = db_mod.get_partial_closes(conn2, trade_id)
    trade_row = conn2.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn2.close()

    labels = [p["tier_label"] for p in partials]
    assert "TIME_STOP" in labels, f"TIME_STOP not fired. Partials: {labels}"

    time_stop = next(p for p in partials if p["tier_label"] == "TIME_STOP")
    assert time_stop["tier"] == 99

    assert trade_row["status"] == "closed", "Trade not finalized after TIME_STOP"


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 5 — Idempotency: calling monitor twice at TP1 price
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario5_idempotency(tmp_db, monkeypatch):
    """Calling monitor_positions twice at TP1 price should fire TP1 only once."""
    conn, db_path, db_mod = tmp_db
    trade_id = _insert_long_trade(db_mod, conn)
    conn.close()

    # First call
    pm = _load_pm(monkeypatch, db_mod, fixed_price=TP1_PRICE)
    pm.monitor_positions()

    # Second call — same price
    pm2 = _load_pm(monkeypatch, db_mod, fixed_price=TP1_PRICE)
    pm2.monitor_positions()

    conn2 = db_mod.get_connection(db_path)
    partials = db_mod.get_partial_closes(conn2, trade_id)
    conn2.close()

    tp1_rows = [p for p in partials if p["tier_label"] == "TP1"]
    assert len(tp1_rows) == 1, (
        f"TP1 should fire exactly once (idempotent), fired {len(tp1_rows)} times"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 6 — initial_sl anchoring: TP2 should NOT fire at a price between
#              TP1 and TP2 after SL was mutated to breakeven
# ═══════════════════════════════════════════════════════════════════════════

def test_scenario6_initial_sl_anchoring(tmp_db, monkeypatch):
    """After TP1 fires (SL→breakeven), a price between TP1 and TP2 must NOT trigger TP2."""
    conn, db_path, db_mod = tmp_db
    trade_id = _insert_long_trade(db_mod, conn)
    conn.close()

    # Phase 1: fire TP1 — SL transitions to breakeven (entry=100)
    pm = _load_pm(monkeypatch, db_mod, fixed_price=TP1_PRICE)
    pm.monitor_positions()

    # Confirm SL is now at breakeven
    conn2 = db_mod.get_connection(db_path)
    trade_row = conn2.execute("SELECT stop_loss FROM trades WHERE id=?", (trade_id,)).fetchone()
    conn2.close()
    assert abs(float(trade_row["stop_loss"]) - ENTRY) < 0.001, (
        f"SL should be at breakeven {ENTRY}, got {trade_row['stop_loss']}"
    )

    # Phase 2: price sits at 103 — between TP1 (102) and TP2 (104)
    # With a naive SL-based r-calc, the new SL=100 would make this look like r=1.5,
    # which could incorrectly trigger TP2 (r=2.0). With initial_sl anchoring this
    # must NOT trigger TP2.
    between_price = 103.0
    pm2 = _load_pm(monkeypatch, db_mod, fixed_price=between_price)
    pm2.monitor_positions()

    conn3 = db_mod.get_connection(db_path)
    partials = db_mod.get_partial_closes(conn3, trade_id)
    conn3.close()

    labels = [p["tier_label"] for p in partials]
    assert "TP2" not in labels, (
        f"TP2 incorrectly fired at price {between_price} (between TP1={TP1_PRICE} and TP2={TP2_PRICE}). "
        f"initial_sl anchoring bug! Partials: {labels}"
    )
    # TP1 should still be there exactly once
    assert labels.count("TP1") == 1
