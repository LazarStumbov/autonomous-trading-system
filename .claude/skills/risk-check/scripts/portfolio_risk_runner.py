"""Portfolio risk snapshot runner.

Computes VaR, CVaR, correlation matrix, and factor exposures across all open
positions, then persists them to portfolio_risk_snapshots +
correlation_matrix_daily. Designed to run on every market_scan cron tick
(hourly) — cheap when no positions are open (early return) and a few
seconds when positions exist (one OHLCV fetch per unique asset).

A Telegram alert fires when:
  * VaR exceeds 4% of capital, OR
  * avg pairwise correlation > 0.75, OR
  * max pairwise correlation > 0.90
…so the user is notified before a slow-roll disaster materializes.

Usage:
  python3 .claude/skills/risk-check/scripts/portfolio_risk_runner.py
  python3 .claude/skills/risk-check/scripts/portfolio_risk_runner.py --no-alert
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib import portfolio_risk as pr  # noqa: E402


# 4% in live mode, 30% in paper (paper allows 250% gross exposure so the same
# 4% ceiling would fire constantly). Tracks the 6% MAX_DAILY_DRAWDOWN: VaR
# crossing 4% means a one-sigma adverse day eats more than half the daily limit.
VAR_PCT_ALERT_THRESHOLD = 30.0 if os.environ.get("PAPER_MODE", "").lower() == "true" else 4.0
CORR_AVG_ALERT_THRESHOLD = 0.75
CORR_MAX_ALERT_THRESHOLD = 0.90


def _maybe_alert(snap: pr.RiskSnapshot) -> None:
    msgs: list[str] = []
    if snap.var_95_pct > VAR_PCT_ALERT_THRESHOLD:
        msgs.append(
            f"VaR 1d 95% = ${snap.var_95_1d_usd:,.2f} ({snap.var_95_pct:.2f}% of capital) "
            f"> {VAR_PCT_ALERT_THRESHOLD}% ceiling"
        )
    if snap.avg_pairwise_correlation and snap.avg_pairwise_correlation > CORR_AVG_ALERT_THRESHOLD:
        msgs.append(f"avg pairwise correlation = {snap.avg_pairwise_correlation:.2f} > {CORR_AVG_ALERT_THRESHOLD}")
    if snap.max_pairwise_correlation and snap.max_pairwise_correlation > CORR_MAX_ALERT_THRESHOLD:
        msgs.append(f"max pairwise correlation = {snap.max_pairwise_correlation:.2f} > {CORR_MAX_ALERT_THRESHOLD}")
    if not msgs:
        return
    try:
        from lib.notifier import send_telegram
        send_telegram(
            "🟠 <b>Portfolio risk warning</b>\n"
            + "\n".join(f"• {m}" for m in msgs)
            + f"\n\nOpen positions: {snap.open_position_count}, gross=${snap.gross_exposure_usd:,.0f}"
        )
    except Exception as e:
        print(f"[portfolio_risk_runner] alert send failed (non-fatal): {e}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--print-only", action="store_true",
                        help="Compute + print, but do not write to DB")
    args = parser.parse_args()

    snap = pr.build_snapshot()
    corr = pr.correlation_matrix(pr.load_open_positions())

    print(
        f"[portfolio_risk] positions={snap.open_position_count} "
        f"gross=${snap.gross_exposure_usd:,.2f} "
        f"net=${snap.net_exposure_usd:,.2f} "
        f"VaR1d95=${snap.var_95_1d_usd:,.2f} ({snap.var_95_pct:.2f}%) "
        f"CVaR=${snap.cvar_95_1d_usd:,.2f} "
        f"avgρ={snap.avg_pairwise_correlation} maxρ={snap.max_pairwise_correlation}"
    )

    if args.print_only:
        return 0

    if snap.open_position_count == 0:
        # Still persist a zero-row so the daily report can show "no positions"
        pr.persist_snapshot(snap)
        return 0

    snap_id = pr.persist_snapshot(snap)
    n_corr = pr.persist_correlation_matrix(corr.get("pairs", {}))
    print(f"[portfolio_risk] snapshot id={snap_id}, {n_corr} correlation pairs persisted")

    if not args.no_alert:
        _maybe_alert(snap)

    return 0


if __name__ == "__main__":
    sys.exit(main())