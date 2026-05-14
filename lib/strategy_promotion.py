"""Strategy promotion gate (Workstream 6 — Stage 6).

Gates the transition `backtest → paper → live`. A strategy can only advance
when its most recent backtest meets ALL hurdle metrics. Otherwise it stays
in its current mode (or gets demoted with a reason on persistent failure).

Hurdles (defaults; can be overridden per asset class in config):
  backtest → paper:
    - trades > 50
    - sharpe > 1.0
    - max_dd_pct < 8
    - win_rate > 0.40 (loose; profit_factor catches the rest)
    - profit_factor > 1.3
  paper → live:
    - 30+ days in paper
    - paper.profit_factor > 1.2
    - paper.max_dd_pct < 6
    - paper.sharpe > 0.7 (paper has higher noise floor)

This module is intentionally pure: it reads strategy_registry +
backtest_results + strategy_performance, decides, and either commits the
mode change or reports the blocking reason. Wiring into a Modal cron is in
modal/trading_webhook.py (weekly_review).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import (  # noqa: E402
    get_connection,
    set_strategy_mode,
    list_strategies,
)

MODE_BACKTEST = "backtest"
MODE_PAPER = "paper"
MODE_LIVE = "live"
MODE_DISABLED = "disabled"


@dataclass
class PromotionHurdles:
    min_trades: int = 50
    min_sharpe: float = 1.0
    max_dd_pct: float = 8.0
    min_win_rate: float = 0.40
    min_profit_factor: float = 1.3


@dataclass
class PaperHurdles:
    min_days: int = 30
    min_sharpe: float = 0.7
    max_dd_pct: float = 6.0
    min_profit_factor: float = 1.2


@dataclass
class Decision:
    strategy_id: str
    current_mode: str
    target_mode: str
    action: str  # 'promote' | 'demote' | 'hold'
    blocking_reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _latest_backtest(conn, strategy_id: str) -> Optional[dict]:
    row = conn.execute(
        """SELECT * FROM backtest_results
            WHERE strategy_id=?
            ORDER BY run_at DESC LIMIT 1""",
        (strategy_id,),
    ).fetchone()
    return dict(row) if row else None


def _paper_perf(conn, strategy_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM strategy_performance WHERE strategy_id=?",
        (strategy_id,),
    ).fetchone()
    return dict(row) if row else None


def _check_backtest_to_paper(bt: dict, hurdles: PromotionHurdles) -> list[str]:
    failures: list[str] = []
    if (bt.get("trades") or 0) < hurdles.min_trades:
        failures.append(f"trades={bt.get('trades')} < {hurdles.min_trades}")
    if (bt.get("sharpe") or 0) < hurdles.min_sharpe:
        failures.append(f"sharpe={bt.get('sharpe')} < {hurdles.min_sharpe}")
    if (bt.get("max_dd_pct") or 100) > hurdles.max_dd_pct:
        failures.append(f"max_dd={bt.get('max_dd_pct')} > {hurdles.max_dd_pct}")
    if (bt.get("win_rate") or 0) < hurdles.min_win_rate:
        failures.append(f"win_rate={bt.get('win_rate')} < {hurdles.min_win_rate}")
    if (bt.get("profit_factor") or 0) < hurdles.min_profit_factor:
        failures.append(f"profit_factor={bt.get('profit_factor')} < {hurdles.min_profit_factor}")
    return failures


def _check_paper_to_live(perf: dict, hurdles: PaperHurdles, mode_changed_at: str | None) -> list[str]:
    failures: list[str] = []
    if mode_changed_at:
        try:
            since = datetime.fromisoformat(mode_changed_at.replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - since).total_seconds() / 86400
            if days < hurdles.min_days:
                failures.append(f"paper_days={days:.1f} < {hurdles.min_days}")
        except (ValueError, AttributeError):
            failures.append("paper_days=unknown")
    if (perf.get("sharpe_30d") or 0) < hurdles.min_sharpe:
        failures.append(f"paper_sharpe={perf.get('sharpe_30d')} < {hurdles.min_sharpe}")
    if (perf.get("max_dd_pct") or 100) > hurdles.max_dd_pct:
        failures.append(f"paper_max_dd={perf.get('max_dd_pct')} > {hurdles.max_dd_pct}")
    if (perf.get("profit_factor") or 0) < hurdles.min_profit_factor:
        failures.append(f"paper_pf={perf.get('profit_factor')} < {hurdles.min_profit_factor}")
    return failures


def evaluate_all(
    bt_hurdles: PromotionHurdles | None = None,
    paper_hurdles: PaperHurdles | None = None,
) -> list[Decision]:
    """Walk every strategy and return the verdict.

    NOTE: returns Decisions but does NOT commit any mode changes. Callers
    (typically the weekly_review cron) iterate and decide whether to apply.
    """
    bt_hurdles = bt_hurdles or PromotionHurdles()
    paper_hurdles = paper_hurdles or PaperHurdles()
    decisions: list[Decision] = []
    conn = get_connection()
    try:
        strategies = list_strategies(conn)
        for s in strategies:
            sid = s["id"]
            mode = s.get("mode") or MODE_BACKTEST
            if mode == MODE_DISABLED:
                continue

            if mode == MODE_BACKTEST:
                bt = _latest_backtest(conn, sid)
                if not bt:
                    decisions.append(Decision(sid, mode, MODE_BACKTEST, "hold",
                                              ["no_backtest_yet"], {}))
                    continue
                fails = _check_backtest_to_paper(bt, bt_hurdles)
                if not fails:
                    decisions.append(Decision(sid, mode, MODE_PAPER, "promote",
                                              [], bt))
                else:
                    decisions.append(Decision(sid, mode, MODE_BACKTEST, "hold",
                                              fails, bt))
                continue

            if mode == MODE_PAPER:
                perf = _paper_perf(conn, sid)
                if not perf:
                    decisions.append(Decision(sid, mode, MODE_PAPER, "hold",
                                              ["no_paper_performance_yet"], {}))
                    continue
                fails = _check_paper_to_live(perf, paper_hurdles, s.get("mode_changed_at"))
                if not fails:
                    decisions.append(Decision(sid, mode, MODE_LIVE, "promote",
                                              [], perf))
                else:
                    decisions.append(Decision(sid, mode, MODE_PAPER, "hold",
                                              fails, perf))
                continue
    finally:
        conn.close()
    return decisions


def apply_decisions(decisions: list[Decision], dry_run: bool = False) -> dict:
    """Commit promote/demote decisions. Returns a summary dict."""
    summary = {"promoted": [], "held": [], "skipped": []}
    if dry_run:
        for d in decisions:
            summary["promoted" if d.action == "promote" else "held"].append({
                "strategy_id": d.strategy_id,
                "from": d.current_mode,
                "to": d.target_mode,
                "reasons": d.blocking_reasons,
            })
        return summary
    conn = get_connection()
    try:
        for d in decisions:
            if d.action == "promote":
                set_strategy_mode(conn, d.strategy_id, d.target_mode,
                                  reason=f"auto_promotion from {d.current_mode}")
                summary["promoted"].append({
                    "strategy_id": d.strategy_id,
                    "from": d.current_mode,
                    "to": d.target_mode,
                })
            else:
                summary["held"].append({
                    "strategy_id": d.strategy_id,
                    "mode": d.current_mode,
                    "reasons": d.blocking_reasons,
                })
    finally:
        conn.close()
    return summary


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Actually commit promotions (default dry-run)")
    args = p.parse_args()
    decisions = evaluate_all()
    summary = apply_decisions(decisions, dry_run=not args.apply)
    print(json.dumps(summary, indent=2, default=str))
