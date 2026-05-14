"""Per-trade post-mortem.

Walks every closed trade whose `reasoning` column does not yet contain a
post-mortem marker and produces one. Also refreshes rolling
`strategy_performance` metrics so the tuner and confluence engine see
up-to-date numbers.

What each post-mortem checks:
  * Stop-loss behaviour: did SL hit and price reverse within N bars? (too tight)
  * Take-profit behaviour: did TP hit but continue running? (too conservative)
  * Backtest delta: how far does the realized pnl_pct sit from the strategy's
    latest backtest win-rate / expectancy snapshot? >2σ = flag.
  * Confluence correlation: was confluence_score high on losers?

Output: a JSON block appended to `trades.reasoning` under a
`---POST-MORTEM---` delimiter so humans can still read prior reasoning.

Run nightly from Modal after the daily report. Idempotent — already-analysed
trades are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection
from lib.strategy_tuner import refresh_all_performance

POST_MORTEM_MARKER = "---POST-MORTEM---"


def _already_analysed(reasoning: str | None) -> bool:
    return bool(reasoning) and POST_MORTEM_MARKER in reasoning


def _latest_backtest_snapshot(conn, strategy_id: str) -> dict | None:
    row = conn.execute(
        "SELECT win_rate, profit_factor, avg_r, sharpe FROM backtest_results "
        "WHERE strategy_id=? AND passed_gate=1 ORDER BY run_at DESC LIMIT 1",
        (strategy_id,),
    ).fetchone()
    return dict(row) if row else None


def _expected_pnl_distribution(conn, strategy_id: str) -> tuple[float | None, float | None]:
    """Return (mean_pnl_pct, stdev_pnl_pct) of recent closed trades for this strategy."""
    rows = conn.execute(
        "SELECT pnl_pct FROM trades WHERE strategy=? AND status='closed' AND pnl_pct IS NOT NULL "
        "ORDER BY closed_at DESC LIMIT 50",
        (strategy_id,),
    ).fetchall()
    pnls = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
    if len(pnls) < 5:
        return None, None
    return statistics.mean(pnls), (statistics.pstdev(pnls) or None)


def _check_tv_replay_divergence(conn, strategy_id: str) -> str | None:
    """Return a flag string if paper win-rate diverges >10% from latest TV replay result.

    TV replay results are written by lib/tv_replay_validator.py to
    data/backtests/tv_replay/. When the divergence exceeds the threshold the
    strategy needs a replay re-run to localise whether the gap is a data-feed
    artefact or a genuine edge decay.
    """
    import glob as _glob
    replay_dir = os.path.join(PROJECT_ROOT, "data", "backtests", "tv_replay")
    pattern = os.path.join(replay_dir, f"{strategy_id.replace('/', '_').replace(':', '_')}__*.json")
    files = sorted(_glob.glob(pattern))
    if not files:
        return None
    try:
        with open(files[-1]) as f:
            replay = json.load(f)
        replay_wr = float(replay.get("win_rate") or 0)
    except Exception:
        return None

    rows = conn.execute(
        "SELECT pnl_usd FROM trades WHERE strategy=? AND status='closed' ORDER BY closed_at DESC LIMIT 30",
        (strategy_id,),
    ).fetchall()
    if len(rows) < 5:
        return None
    paper_wins = sum(1 for r in rows if (r["pnl_usd"] or 0) > 0)
    paper_wr = paper_wins / len(rows)

    divergence = abs(paper_wr - replay_wr)
    if divergence >= 0.10:
        return (
            f"TV replay divergence: paper_wr={paper_wr:.2f} vs replay_wr={replay_wr:.2f} "
            f"(Δ={divergence:.2f}) — re-run tv_replay_validator to localise gap."
        )
    return None


def analyse_trade(conn, trade: dict) -> dict:
    """Return a post-mortem dict for a single closed trade."""
    notes: list[str] = []
    flags: list[str] = []

    entry = trade.get("entry_price") or 0
    exit_price = trade.get("exit_price") or 0
    sl = trade.get("stop_loss")
    tp = trade.get("take_profit")
    direction = trade.get("direction")
    pnl_pct = trade.get("pnl_pct") or 0
    confluence = trade.get("confluence_score")
    strategy = trade.get("strategy")

    # Stop / TP hit detection
    sl_hit = False
    tp_hit = False
    if sl and exit_price:
        # Long: exit at or below SL ⇒ SL hit. Short: exit at or above SL.
        if direction == "long" and exit_price <= sl * 1.0005:
            sl_hit = True
        elif direction == "short" and exit_price >= sl * 0.9995:
            sl_hit = True
    if tp and exit_price:
        if direction == "long" and exit_price >= tp * 0.9995:
            tp_hit = True
        elif direction == "short" and exit_price <= tp * 1.0005:
            tp_hit = True

    if sl_hit:
        notes.append(f"Stop-loss triggered (direction={direction}, exit={exit_price}, SL={sl}).")
    if tp_hit:
        notes.append(f"Take-profit triggered (direction={direction}, exit={exit_price}, TP={tp}).")

    # Risk-reward realised
    if sl and tp and entry:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        planned_rr = reward / risk if risk else None
        if planned_rr is not None:
            notes.append(f"Planned R:R was {planned_rr:.2f}.")

    # Backtest delta
    if strategy:
        snap = _latest_backtest_snapshot(conn, strategy)
        if snap and snap.get("avg_r") is not None:
            notes.append(f"Backtest expectancy (avg R): {snap['avg_r']:.2f}.")
        mean, stdev = _expected_pnl_distribution(conn, strategy)
        if mean is not None and stdev:
            z = (pnl_pct - mean) / stdev if stdev else 0
            if abs(z) >= 2:
                flags.append(f"pnl_pct={pnl_pct:.2f}% is {z:+.1f}σ from recent mean {mean:.2f}%.")

    # Confluence correlation flag
    if confluence is not None and pnl_pct is not None:
        if confluence >= 80 and pnl_pct < 0:
            flags.append(f"High-confluence ({confluence:.0f}) loss — review signal weights.")
        if confluence < 60 and pnl_pct > 0:
            notes.append(f"Low-confluence ({confluence:.0f}) winner — lucky or over-filtered?")

    # TV replay divergence flag — compare paper win-rate against latest TV replay result
    if strategy:
        tv_flag = _check_tv_replay_divergence(conn, strategy)
        if tv_flag:
            flags.append(tv_flag)

    verdict = "win" if pnl_pct > 0 else "loss" if pnl_pct < 0 else "scratch"

    return {
        "verdict": verdict,
        "pnl_pct": round(pnl_pct, 3),
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "flags": flags,
        "notes": notes,
        "analysed_at": datetime.now(timezone.utc).isoformat(),
    }


def _append_post_mortem(conn, trade_id: int, pm: dict, existing_reasoning: str | None) -> None:
    existing = (existing_reasoning or "").rstrip()
    block = f"\n\n{POST_MORTEM_MARKER}\n{json.dumps(pm, indent=2)}"
    combined = existing + block
    conn.execute("UPDATE trades SET reasoning=? WHERE id=?", (combined, trade_id))
    conn.commit()


def run(limit: int | None = None) -> dict:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC"
        ).fetchall()
        analysed = 0
        skipped = 0
        flagged = 0
        for r in rows:
            trade = dict(r)
            if _already_analysed(trade.get("reasoning")):
                skipped += 1
                continue
            pm = analyse_trade(conn, trade)
            _append_post_mortem(conn, trade["id"], pm, trade.get("reasoning"))
            analysed += 1
            if pm["flags"]:
                flagged += 1
            if limit and analysed >= limit:
                break

        # Refresh per-strategy rolling metrics so the tuner has fresh numbers
        try:
            refresh_all_performance()
            perf_refreshed = True
        except Exception as e:
            perf_refreshed = False
            print(f"[trade_analyzer] warning: refresh_all_performance failed: {e}")

        summary = {
            "analysed": analysed,
            "skipped_already_done": skipped,
            "flagged": flagged,
            "perf_refreshed": perf_refreshed,
        }
        print(f"[trade_analyzer] {summary}")
        return summary
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Max trades to analyse this run")
    args = ap.parse_args()
    run(limit=args.limit)


if __name__ == "__main__":
    main()
