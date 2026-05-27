"""Strategy tuner: applies promotion and demotion decisions based on live/paper performance.

Runs nightly (and on demand). Reads closed trades per strategy, computes rolling
metrics, and transitions modes according to config/strategy_gates.json.

Transitions handled here:
  - paper → live  : when paper performance tracks backtest expectations and the
                    strategy has traded enough days/signals.
  - live → paper  : on rolling performance deterioration (demotion).
  - paper → disabled : after 2 consecutive paper gate failures.
  - circuit breaker : if weekly Sharpe across auto-applied strategies < 0, pause
                      new hypothesis generation for 7 days.

NOTE: backtest → paper transitions live in lib/backtester.py's `promote_all`.
This file handles everything after a strategy already has a DB history.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import (
    get_connection,
    list_strategies,
    get_strategy,
    set_strategy_mode,
    upsert_strategy_performance,
    set_system_state,
    get_system_state,
)

GATES_PATH = os.path.join(PROJECT_ROOT, "config", "strategy_gates.json")


def load_gates() -> dict:
    with open(GATES_PATH) as f:
        return json.load(f)


# ── Metrics from closed trades ───────────────────────────────────────────────
def _trades_for_strategy(conn, strategy_id: str, since_iso: str = None) -> list[dict]:
    q = "SELECT * FROM trades WHERE strategy=? AND status='closed'"
    params: list = [strategy_id]
    if since_iso:
        q += " AND closed_at >= ?"
        params.append(since_iso)
    q += " ORDER BY closed_at ASC"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def compute_metrics(trades: list[dict]) -> dict:
    """Compute the rolling metrics needed to evaluate paper/live gates."""
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_30d": 0.0,
            "last_20_win_rate": 0.0,
            "total_pnl_usd": 0.0,
            "consecutive_losses": 0,
            "max_single_day_loss_pct": 0.0,
        }
    n = len(trades)
    wins = [t for t in trades if (t.get("pnl_usd") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl_usd") or 0) <= 0]
    gross_wins = sum(t["pnl_usd"] for t in wins)
    gross_losses = abs(sum(t["pnl_usd"] for t in losses))
    pf = (gross_wins / gross_losses) if gross_losses > 0 else (float("inf") if gross_wins > 0 else 0.0)

    last_20 = trades[-20:]
    last_20_wr = sum(1 for t in last_20 if (t.get("pnl_usd") or 0) > 0) / len(last_20) if last_20 else 0.0

    # 30-day Sharpe approximation — requires ≥ 3 trades; single-trade std is 0
    # which produces a divide-by-1e-9 artefact in the billions.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = [t for t in trades if t.get("closed_at") and datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00")) >= cutoff]
    if len(recent) >= 3:
        rets = [t.get("pnl_pct") or 0 for t in recent]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        std = math.sqrt(var) if var > 0 else None
        sharpe_30d = (mean / std) * math.sqrt(252) if std else 0.0
    else:
        sharpe_30d = 0.0

    # Consecutive losses (streak ending at last trade)
    streak = 0
    for t in reversed(trades):
        if (t.get("pnl_usd") or 0) <= 0:
            streak += 1
        else:
            break

    # Worst single-day loss %
    by_day: dict[str, float] = {}
    for t in trades:
        if not t.get("closed_at"):
            continue
        day = t["closed_at"][:10]
        by_day[day] = by_day.get(day, 0.0) + (t.get("pnl_pct") or 0)
    max_single_day_loss_pct = abs(min(by_day.values())) if by_day else 0.0

    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / n,
        "profit_factor": pf if pf != float("inf") else 999.0,
        "sharpe_30d": sharpe_30d,
        "last_20_win_rate": last_20_wr,
        "total_pnl_usd": sum(t.get("pnl_usd") or 0 for t in trades),
        "consecutive_losses": streak,
        "max_single_day_loss_pct": max_single_day_loss_pct,
    }


def refresh_strategy_performance(conn, strategy_id: str) -> None:
    """Recompute the strategy_performance row for one strategy from its closed trades.

    Called from position_monitor._finalize_trade right after a trade is marked
    closed, so aggregated metrics (win rate, profit factor, etc.) never go stale
    relative to the journal. Cheap — one strategy at a time, no full table scan.
    """
    strat = get_strategy(conn, strategy_id)
    trades = _trades_for_strategy(conn, strategy_id)
    m = compute_metrics(trades)
    upsert_strategy_performance(
        conn,
        strategy_id,
        mode=strat["mode"] if strat else "paper",
        total_trades=m["total_trades"],
        winning_trades=m.get("winning_trades", 0),
        losing_trades=m.get("losing_trades", 0),
        total_pnl_usd=m["total_pnl_usd"],
        profit_factor=m["profit_factor"],
        win_rate=m["win_rate"],
        last_20_win_rate=m["last_20_win_rate"],
        sharpe_30d=m["sharpe_30d"],
        consecutive_losses=m["consecutive_losses"],
        last_trade_at=trades[-1]["closed_at"] if trades else None,
    )


def refresh_all_performance() -> None:
    """Recompute strategy_performance rows for every registered strategy."""
    conn = get_connection()
    try:
        for s in list_strategies(conn):
            refresh_strategy_performance(conn, s["id"])
    finally:
        conn.close()


# ── Promotion / demotion decisions ───────────────────────────────────────────
def _paper_gate_result(conn, strategy_row: dict, metrics: dict, gates: dict) -> tuple[bool, list[str]]:
    g = gates.get("paper_to_live", {})
    reasons: list[str] = []

    if metrics["total_trades"] < g.get("min_paper_signals", 10):
        reasons.append(f"signals {metrics['total_trades']} < {g.get('min_paper_signals', 10)}")

    mode_changed = strategy_row.get("mode_changed_at")
    days_in_paper = 0
    if mode_changed:
        try:
            days_in_paper = (datetime.now(timezone.utc) - datetime.fromisoformat(mode_changed.replace("Z", "+00:00"))).days
        except Exception:
            days_in_paper = 0
    if days_in_paper < g.get("min_paper_days", 14):
        reasons.append(f"paper_days {days_in_paper} < {g.get('min_paper_days', 14)}")

    # Paper vs backtest deviation check
    backtest_snap = strategy_row.get("backtest_snapshot_json")
    if backtest_snap:
        try:
            snap = json.loads(backtest_snap)
            bt_wr = snap.get("win_rate", 0.0)
            dev_max = g.get("paper_vs_backtest_winrate_deviation_max", 0.20)
            if abs(metrics["win_rate"] - bt_wr) > dev_max:
                reasons.append(f"paper_wr {metrics['win_rate']:.2f} deviates from backtest_wr {bt_wr:.2f} by > {dev_max}")
        except Exception:
            pass

    if metrics["max_single_day_loss_pct"] > g.get("no_single_day_loss_pct_above", 5.0):
        reasons.append(f"single_day_loss {metrics['max_single_day_loss_pct']:.2f}% > {g.get('no_single_day_loss_pct_above', 5.0)}%")

    # TV replay gate — if a replay result exists, block promotion when
    # paper win-rate diverges from replay win-rate by more than the threshold.
    # Strategies flagged needs_tv_replay must have a replay result before they
    # can pass this gate.
    replay_flag = get_system_state(conn, f"needs_tv_replay:{strategy_row['id']}")
    if replay_flag == "true":
        tv_replay_wr = _latest_tv_replay_win_rate(strategy_row["id"])
        if tv_replay_wr is None:
            reasons.append("TV replay result required before paper→live promotion (run tv_replay_validator)")
        else:
            max_dev = g.get("paper_vs_tv_replay_winrate_deviation_max", 0.15)
            divergence = abs(metrics.get("win_rate", 0) - tv_replay_wr)
            if divergence > max_dev:
                reasons.append(
                    f"TV replay divergence: paper_wr={metrics.get('win_rate', 0):.2f} "
                    f"vs replay_wr={tv_replay_wr:.2f} (Δ={divergence:.2f} > {max_dev})"
                )

    return (len(reasons) == 0, reasons)


def _latest_tv_replay_win_rate(strategy_id: str) -> float | None:
    """Read the win_rate from the most recent TV replay result for this strategy.
    Returns None if no replay file exists yet."""
    import glob as _glob
    replay_dir = os.path.join(PROJECT_ROOT, "data", "backtests", "tv_replay")
    safe_id = strategy_id.replace("/", "_").replace(":", "_")
    files = sorted(_glob.glob(os.path.join(replay_dir, f"{safe_id}__*.json")))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            import json as _json
            data = _json.load(f)
        return float(data.get("win_rate") or 0)
    except Exception:
        return None


def _demotion_triggered(metrics: dict, gates: dict) -> tuple[bool, list[str]]:
    g = gates.get("live_to_paper_demotion", {})
    reasons: list[str] = []
    lookback = g.get("last_n_trades_lookback", 20)
    min_wr = g.get("last_n_trades_min_winrate", 0.40)
    if metrics["total_trades"] >= lookback and metrics["last_20_win_rate"] < min_wr:
        reasons.append(f"last_{lookback}_wr {metrics['last_20_win_rate']:.2f} < {min_wr}")

    if metrics["profit_factor"] < g.get("min_profit_factor_30d", 1.0):
        reasons.append(f"pf_30d {metrics['profit_factor']:.2f} < {g.get('min_profit_factor_30d', 1.0)}")

    if metrics["consecutive_losses"] >= g.get("max_consecutive_losses", 5):
        reasons.append(f"consecutive_losses {metrics['consecutive_losses']} >= {g.get('max_consecutive_losses', 5)}")

    return (len(reasons) > 0, reasons)


def apply_transitions() -> list[dict]:
    """Walk every paper and live strategy. Promote/demote as gates dictate.
    Returns a list of transition records for logging/notifications."""
    gates = load_gates()
    transitions: list[dict] = []
    conn = get_connection()
    try:
        strategies = list_strategies(conn)
        for s in strategies:
            sid = s["id"]
            mode = s["mode"]
            if mode not in ("paper", "live"):
                continue
            trades = _trades_for_strategy(conn, sid)
            metrics = compute_metrics(trades)

            if mode == "paper":
                passed, reasons = _paper_gate_result(conn, s, metrics, gates)
                if passed:
                    set_strategy_mode(conn, sid, "live", reason="paper gate passed")
                    transitions.append({"strategy": sid, "from": "paper", "to": "live", "reasons": reasons})
                else:
                    # Accumulate paper failures for paper → disabled
                    fails_raw = get_system_state(conn, f"paper_fails:{sid}") or "0"
                    try:
                        fails = int(fails_raw)
                    except ValueError:
                        fails = 0
                    # Only count a "failure" if enough signals elapsed
                    if metrics["total_trades"] >= gates.get("paper_to_live", {}).get("min_paper_signals", 10):
                        fails += 1
                        set_system_state(conn, f"paper_fails:{sid}", str(fails))
                        if fails >= gates.get("paper_to_disabled", {}).get("consecutive_paper_gate_failures", 2):
                            set_strategy_mode(conn, sid, "disabled", reason=f"2x paper gate failure: {'; '.join(reasons)}")
                            transitions.append({"strategy": sid, "from": "paper", "to": "disabled", "reasons": reasons})

            elif mode == "live":
                demote, reasons = _demotion_triggered(metrics, gates)
                if demote:
                    set_strategy_mode(conn, sid, "paper", reason=f"live demotion: {'; '.join(reasons)}")
                    transitions.append({"strategy": sid, "from": "live", "to": "paper", "reasons": reasons})
    finally:
        conn.close()
    return transitions


# ── Circuit breaker on the self-improvement loop itself ──────────────────────
def loop_circuit_breaker_check() -> tuple[bool, str]:
    """If weekly Sharpe across auto-applied strategies is negative, pause the
    hypothesis generator for N days. Returns (tripped, message)."""
    gates = load_gates()
    cfg = gates.get("loop_circuit_breaker", {})
    min_sharpe = cfg.get("weekly_sharpe_auto_applied_min", 0.0)
    pause_days = cfg.get("pause_duration_days", 7)

    conn = get_connection()
    try:
        # "Auto-applied" = strategies whose id was generated by hypothesis_generator
        rows = conn.execute(
            "SELECT new_strategy_id FROM strategy_hypotheses WHERE status IN ('in_paper','live')"
        ).fetchall()
        auto_ids = [r["new_strategy_id"] for r in rows if r["new_strategy_id"]]
        if not auto_ids:
            return False, "no auto-applied strategies yet"

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        returns: list[float] = []
        for sid in auto_ids:
            trades = _trades_for_strategy(conn, sid, since_iso=cutoff)
            for t in trades:
                returns.append(t.get("pnl_pct") or 0)
        if not returns:
            return False, "no recent auto-applied trades"
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / len(returns)
        std = math.sqrt(var) if var > 0 else 1e-9
        weekly_sharpe = (mean / std) * math.sqrt(52) if std > 0 else 0.0

        if weekly_sharpe < min_sharpe:
            resume_at = (datetime.now(timezone.utc) + timedelta(days=pause_days)).isoformat()
            set_system_state(conn, "hypothesis_loop_paused_until", resume_at)
            return True, f"weekly_sharpe {weekly_sharpe:.2f} < {min_sharpe}; paused until {resume_at}"
        return False, f"weekly_sharpe {weekly_sharpe:.2f} OK"
    finally:
        conn.close()


# ── Auto-promote / archive ───────────────────────────────────────────────────

_AUDIT_LOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memory", "STRATEGY-AUDIT.md")


def _ensure_extended_modes(conn) -> None:
    """Add 'archived' and 'backtest_validated' to the strategy_registry mode CHECK.

    SQLite doesn't support ALTER COLUMN. We do a table-swap migration using a
    separate raw connection so PRAGMA foreign_keys = OFF takes effect outside
    any active transaction. Safe to call repeatedly (idempotent).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='strategy_registry'"
    ).fetchone()
    if not row or "archived" in row[0]:
        return

    import sqlite3 as _sqlite3
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    raw = _sqlite3.connect(db_path, isolation_level=None)  # autocommit
    try:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("BEGIN")
        raw.execute("DROP TABLE IF EXISTS strategy_registry_new")
        raw.execute("""
            CREATE TABLE strategy_registry_new (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                source TEXT,
                source_url TEXT,
                source_commit TEXT,
                license TEXT,
                version TEXT,
                class_path TEXT,
                timeframes_json TEXT,
                asset_classes_json TEXT,
                mode TEXT NOT NULL CHECK (mode IN (
                    'backtest', 'paper', 'live', 'disabled', 'archived', 'backtest_validated'
                )) DEFAULT 'backtest',
                params_json TEXT,
                safe_bounds_json TEXT,
                backtest_snapshot_json TEXT,
                paper_snapshot_json TEXT,
                risk_notes TEXT,
                mode_changed_at TEXT,
                demotion_reason TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        raw.execute("INSERT INTO strategy_registry_new SELECT * FROM strategy_registry")
        raw.execute("DROP TABLE strategy_registry")
        raw.execute("ALTER TABLE strategy_registry_new RENAME TO strategy_registry")
        raw.execute("CREATE INDEX IF NOT EXISTS idx_strategy_mode ON strategy_registry(mode)")
        raw.execute("COMMIT")
        raw.execute("PRAGMA foreign_keys = ON")
    except Exception:
        raw.execute("ROLLBACK")
        raw.execute("PRAGMA foreign_keys = ON")
        raise
    finally:
        raw.close()


def _append_audit(entry: str) -> None:
    os.makedirs(os.path.dirname(_AUDIT_LOG), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(_AUDIT_LOG, "a") as f:
        f.write(f"- [{ts}] {entry}\n")


def auto_promote_demote() -> list[dict]:
    """Paper-mode auto-tuner: archive chronic losers, promote consistent winners.

    Thresholds (paper-mode relaxed vs live):
      Archive:  win_rate < 0.30  AND  total_trades >= 3  (live: >= 5)
      Promote:  profit_factor >= 1.5  AND  total_trades >= 5  (live: >= 10)
        paper → backtest_validated

    Returns a list of action dicts for logging.
    """
    paper_mode = os.environ.get("PAPER_MODE", "").lower() == "true"
    min_trades_archive = 2 if paper_mode else 5
    min_trades_promote = 5 if paper_mode else 10

    conn = get_connection()
    _ensure_extended_modes(conn)
    actions: list[dict] = []

    try:
        for s in list_strategies(conn):
            sid = s["id"]
            mode = s["mode"]
            if mode in ("archived", "disabled", "live"):
                continue
            trades = _trades_for_strategy(conn, sid)
            metrics = compute_metrics(trades)
            n = metrics["total_trades"]

            # Archive: chronic loser
            if mode == "paper" and n >= min_trades_archive and metrics["win_rate"] < 0.30:
                set_strategy_mode(conn, sid, "archived",
                                  reason=f"win_rate={metrics['win_rate']:.2f} < 0.30 over {n} trades")
                msg = (f"ARCHIVED {sid}: win_rate={metrics['win_rate']:.2f} "
                       f"pnl=${metrics['total_pnl_usd']:.2f} n={n}")
                _append_audit(msg)
                actions.append({"strategy": sid, "action": "archived", "reason": msg})

            # Promote: consistent paper performer
            elif mode == "paper" and n >= min_trades_promote and metrics["profit_factor"] >= 1.5:
                set_strategy_mode(conn, sid, "backtest_validated",
                                  reason=f"pf={metrics['profit_factor']:.2f} over {n} trades")
                msg = (f"PROMOTED {sid}: profit_factor={metrics['profit_factor']:.2f} "
                       f"win_rate={metrics['win_rate']:.2f} n={n}")
                _append_audit(msg)
                actions.append({"strategy": sid, "action": "promoted", "reason": msg})

    finally:
        conn.close()

    if actions:
        print(f"[auto_promote_demote] {len(actions)} action(s):")
        for a in actions:
            print(f"  {a['action'].upper()}: {a['strategy']} — {a['reason']}")
    else:
        print("[auto_promote_demote] no changes (thresholds not met)")
    return actions


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Apply promotion/demotion to strategies")
    parser.add_argument("--refresh", action="store_true", help="Recompute strategy_performance from trade journal")
    parser.add_argument("--transitions", action="store_true", help="Apply paper/live transitions")
    parser.add_argument("--circuit-breaker", action="store_true", help="Check auto-loop circuit breaker")
    parser.add_argument("--auto-tune", action="store_true", help="Archive losers, promote winners")
    parser.add_argument("--all", action="store_true", help="Run all four")
    args = parser.parse_args()

    if args.all or args.refresh:
        refresh_all_performance()
        print("[tuner] performance refreshed")

    if args.all or args.transitions:
        transitions = apply_transitions()
        print(f"[tuner] {len(transitions)} transitions:")
        for t in transitions:
            print(f"  {t['strategy']} {t['from']} → {t['to']}: {'; '.join(t['reasons'])}")

    if args.all or args.auto_tune:
        auto_promote_demote()

    if args.all or args.circuit_breaker:
        tripped, msg = loop_circuit_breaker_check()
        print(f"[tuner] circuit_breaker: {'TRIPPED' if tripped else 'ok'} — {msg}")


if __name__ == "__main__":
    main()
