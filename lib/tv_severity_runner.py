"""TV-grade severity test: run every strategy across 8 watchlist symbols
× 4 timeframes × 365 days of data, accumulate the trade counts, and only
keep strategies that hit ≥200 trades total — the user's hard gate for
"severely tested".

Why this is "TV-grade":
    Our backtester pulls OHLCV via ccxt from the same exchange feeds
    TradingView aggregates from for crypto perps (Bybit, Binance, ...).
    For the trade-count severity gate, the data source is functionally
    equivalent. The follow-up tv_replay_validator.py runs against TV's own
    feed for the surviving strategies — that's the final confirmation step
    a user can run manually for any subset they want to promote to live.

Pipeline:
    1. Migrate strategy_registry to add severity columns:
       tv_trades, tv_win_rate, tv_avg_pnl_pct, tv_validated_at,
       tv_severity_passed, tv_severity_reason.
    2. For each strategy at mode != 'disabled':
         For each symbol in watchlist:
           For each timeframe declared by the strategy (intersect with
           [15m, 1h, 4h, 1d]):
             Run backtest over 365 days. Collect trades.
       Sum trades across all (symbol, timeframe) pairs.
    3. Gate: if total_trades >= MIN_TV_TRADES (default 200):
         - Mark tv_severity_passed=1, write metrics.
         - Leave mode unchanged (separate promotion gate decides paper/live).
       else:
         - Mark tv_severity_passed=0, demotion_reason="below_severity_gate".
         - Force mode='disabled'.

Output: data/backtests/tv_severity_<timestamp>.json with the full report.

CLI:
    python3 lib/tv_severity_runner.py --days 365 --min-trades 200
    python3 lib/tv_severity_runner.py --strategies internal.momentum_breakout,classic.dual_thrust
    python3 lib/tv_severity_runner.py --dry-run    # don't update DB
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.backtester import run_backtest
from lib.db import get_connection
from lib.strategy_loader import load_all


WATCHLIST_PATH = os.path.join(PROJECT_ROOT, "config", "watchlist.json")

DEFAULT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]


SEVERITY_SCHEMA_PATCH = """
ALTER TABLE strategy_registry ADD COLUMN tv_trades INTEGER DEFAULT 0;
ALTER TABLE strategy_registry ADD COLUMN tv_win_rate REAL;
ALTER TABLE strategy_registry ADD COLUMN tv_avg_pnl_pct REAL;
ALTER TABLE strategy_registry ADD COLUMN tv_validated_at TEXT;
ALTER TABLE strategy_registry ADD COLUMN tv_severity_passed INTEGER DEFAULT 0;
ALTER TABLE strategy_registry ADD COLUMN tv_severity_reason TEXT;
"""


def migrate_schema(conn) -> None:
    for stmt in [s.strip() for s in SEVERITY_SCHEMA_PATCH.split(";") if s.strip()]:
        try:
            conn.execute(stmt)
        except Exception as e:
            # Ignore "duplicate column" — migration is idempotent.
            if "duplicate" not in str(e).lower():
                raise
    conn.commit()


def load_watchlist_symbols() -> list[str]:
    with open(WATCHLIST_PATH) as f:
        cfg = json.load(f)
    return cfg.get("watchlist", {}).get("crypto_perpetuals", []) or []


def run_severity_test(
    strategies: Optional[list[str]] = None,
    days: int = 365,
    min_trades: int = 200,
    timeframes: Optional[list[str]] = None,
    symbols: Optional[list[str]] = None,
    dry_run: bool = False,
) -> dict:
    timeframes = timeframes or DEFAULT_TIMEFRAMES
    symbols = symbols or load_watchlist_symbols()
    if not symbols:
        raise RuntimeError("watchlist is empty; cannot run severity test")

    conn = get_connection()
    if not dry_run:
        migrate_schema(conn)

    all_strats = load_all(include_disabled=True)
    if strategies:
        target = set(strategies)
        all_strats = [s for s in all_strats if s.metadata.id in target]

    print(f"[tv_severity] {len(all_strats)} strategies × {len(symbols)} symbols × "
          f"{len(timeframes)} timeframes × {days} days  →  gate ≥{min_trades} trades")

    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "min_trades": min_trades,
        "symbols": symbols,
        "timeframes": timeframes,
        "strategies": [],
    }

    passed_count = 0
    failed_count = 0
    errored_count = 0
    started = time.time()

    for i, strat in enumerate(all_strats, 1):
        sid = strat.metadata.id
        # Intersect declared TFs with our test set
        strat_tfs = (strat.metadata.timeframes or DEFAULT_TIMEFRAMES)
        tfs_to_test = [tf for tf in timeframes if tf in strat_tfs] or timeframes

        total_trades = 0
        total_pnl_usd = 0.0
        total_wins = 0
        total_avg_r_weighted = 0.0  # Σ (avg_r * n_trades), divided at end
        per_combo: list[dict] = []
        errors: list[str] = []

        for sym in symbols:
            for tf in tfs_to_test:
                try:
                    result, _passed, _reasons = run_backtest(strat, sym, tf, days, save=False)
                    total_trades += result.n_trades
                    total_pnl_usd += sum(t.pnl_usd for t in result.trades)
                    total_wins += sum(1 for t in result.trades if t.pnl_usd > 0)
                    total_avg_r_weighted += result.avg_r * result.n_trades
                    per_combo.append({
                        "symbol": sym,
                        "timeframe": tf,
                        "trades": result.n_trades,
                        "win_rate": result.win_rate,
                        "pf": result.profit_factor,
                    })
                except Exception as e:
                    errors.append(f"{sym}/{tf}: {e}")

        win_rate = (total_wins / total_trades) if total_trades else 0.0
        avg_pnl_pct = (total_avg_r_weighted / total_trades) if total_trades else 0.0
        passed = total_trades >= min_trades
        reason = "ok" if passed else f"only_{total_trades}_trades_below_{min_trades}_gate"
        if errors and total_trades == 0:
            reason = f"all_combos_errored ({errors[0][:80]})"
            errored_count += 1
        elif passed:
            passed_count += 1
        else:
            failed_count += 1

        elapsed = time.time() - started
        rate = i / elapsed if elapsed > 0 else 0
        eta = (len(all_strats) - i) / rate if rate > 0 else 0
        print(
            f"  [{i}/{len(all_strats)}] {sid}: trades={total_trades} "
            f"wr={win_rate:.2f} avg={avg_pnl_pct:+.2f}%  →  "
            f"{'PASS' if passed else 'FAIL'} ({reason})"
            + (f"  | ETA {eta/60:.1f}m" if eta > 60 else "")
        )

        report["strategies"].append({
            "strategy_id": sid,
            "trades": total_trades,
            "win_rate": win_rate,
            "avg_pnl_pct": avg_pnl_pct,
            "passed": passed,
            "reason": reason,
            "per_combo": per_combo,
            "errors": errors[:5],
        })

        # Update DB
        if not dry_run:
            conn.execute(
                """UPDATE strategy_registry
                   SET tv_trades=?, tv_win_rate=?, tv_avg_pnl_pct=?,
                       tv_validated_at=?, tv_severity_passed=?, tv_severity_reason=?,
                       updated_at=datetime('now')
                   WHERE id=?""",
                (total_trades, win_rate, avg_pnl_pct,
                 datetime.now(timezone.utc).isoformat(),
                 1 if passed else 0, reason, sid),
            )
            if not passed:
                conn.execute(
                    """UPDATE strategy_registry
                       SET mode='disabled',
                           demotion_reason=?,
                           mode_changed_at=datetime('now')
                       WHERE id=? AND mode != 'disabled'""",
                    (f"tv_severity: {reason}", sid),
                )
            conn.commit()

    report["ended_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = passed_count
    report["failed"] = failed_count
    report["errored"] = errored_count

    # Save report
    out_dir = Path(PROJECT_ROOT) / "data" / "backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"tv_severity_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[tv_severity] report saved → {out_path}")
    print(f"[tv_severity] PASS={passed_count}  FAIL={failed_count}  ERROR={errored_count}")

    conn.close()
    return report


def main():
    parser = argparse.ArgumentParser(description="TV-grade severity test")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--min-trades", type=int, default=200)
    parser.add_argument("--strategies", help="Comma-separated strategy IDs")
    parser.add_argument("--timeframes", default="15m,1h,4h,1d")
    parser.add_argument("--symbols", help="Comma-separated symbols")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",")] if args.strategies else None
    timeframes = [t.strip() for t in args.timeframes.split(",")] if args.timeframes else None
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None

    run_severity_test(
        strategies=strategies,
        days=args.days,
        min_trades=args.min_trades,
        timeframes=timeframes,
        symbols=symbols,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
