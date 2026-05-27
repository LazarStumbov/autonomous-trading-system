"""Performance metric helpers for the dashboard."""
from __future__ import annotations
import math
from typing import Any


def compute_metrics(trades: list[dict], daily_rows: list[dict]) -> dict[str, Any]:
    """Compute Sharpe, Sortino, Calmar, win rate, etc. from closed trades + daily_pnl rows."""
    if not trades:
        return _empty_metrics()

    closed = [t for t in trades if t.get("pnl_usd") is not None]
    if not closed:
        return _empty_metrics()

    pnls = [float(t["pnl_usd"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0  # negative
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * abs(avg_loss)) * (1 if avg_win > 0 else -1)
    profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    # Consecutive max loss streak
    max_consec = _max_consecutive_losses(pnls)

    # Sharpe and Sortino from daily returns
    sharpe = None
    sortino = None
    calmar = None
    max_dd_pct = None

    if daily_rows:
        capitals = [float(r.get("ending_capital") or 0) for r in daily_rows if r.get("ending_capital")]
        daily_rets = []
        for i in range(1, len(capitals)):
            if capitals[i - 1] > 0:
                daily_rets.append((capitals[i] - capitals[i - 1]) / capitals[i - 1])

        if len(daily_rets) >= 2:
            mean_r = sum(daily_rets) / len(daily_rets)
            std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_rets) / (len(daily_rets) - 1))
            if std_r > 0:
                sharpe = round((mean_r / std_r) * math.sqrt(252), 2)

            downside = [r for r in daily_rets if r < 0]
            if downside:
                down_std = math.sqrt(sum(r ** 2 for r in downside) / len(downside))
                if down_std > 0:
                    sortino = round((mean_r / down_std) * math.sqrt(252), 2)

        # Max drawdown from equity curve
        if capitals:
            peak = capitals[0]
            max_dd = 0.0
            for c in capitals:
                if c > peak:
                    peak = c
                dd = (peak - c) / peak if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            max_dd_pct = round(max_dd * 100, 2)

            # Calmar = annualized return / max DD
            if len(capitals) >= 2 and max_dd > 0:
                total_ret = (capitals[-1] - capitals[0]) / capitals[0] if capitals[0] > 0 else 0
                ann_ret = total_ret * (365 / len(capitals))
                calmar = round(ann_ret / max_dd, 2)

    return {
        "total_trades": len(closed),
        "win_rate": round(win_rate * 100, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "max_consecutive_losses": max_consec,
        "sharpe_30d": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown_pct": max_dd_pct,
        "total_pnl": round(sum(pnls), 2),
    }


def _empty_metrics() -> dict:
    return {
        "total_trades": 0,
        "win_rate": 0,
        "avg_win": 0,
        "avg_loss": 0,
        "expectancy": 0,
        "profit_factor": 0,
        "max_consecutive_losses": 0,
        "sharpe_30d": None,
        "sortino": None,
        "calmar": None,
        "max_drawdown_pct": None,
        "total_pnl": 0,
    }


def _max_consecutive_losses(pnls: list[float]) -> int:
    max_c = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_c = max(max_c, cur)
        else:
            cur = 0
    return max_c
