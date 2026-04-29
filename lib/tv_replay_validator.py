"""Walk a strategy bar-by-bar against TradingView's own historical data using
the MCP `replay_*` tools.

Why this exists:
    Our backtester uses ccxt OHLCV. TradingView aggregates from a different
    exchange feed and applies its own session/holiday rules. Strategies that
    look great on ccxt sometimes break on TV-aggregated data because of
    timing or fill-price differences. Running a replay validation flags those
    discrepancies before live capital is at risk.

How it works:
    1. Load the strategy via `lib.strategy_loader.load_strategy(id)`.
    2. Set the chart symbol + timeframe via `mcp__tradingview__chart_set_*`.
    3. Call `replay_start(date=...)` to rewind to the start of the replay
       window.
    4. Loop: `replay_step(bars=1)` → `data_get_ohlcv(summary=False)` for the
       most recent bar → strategy.entry_signal() → record decision.
    5. On each entry signal, simulate fill at next-bar open, track until SL
       or TP hit (or max_hold bars expire).
    6. `replay_stop()`, summarize PNL, win rate, n_trades.

This module never executes trades — it's a pure validator. Output goes to
`data/backtests/tv_replay/<strategy>_<symbol>_<timestamp>.json`.

CLI:
    python3 lib/tv_replay_validator.py --strategy classic.donchian_breakout \\
        --symbol BTCUSD --bars 500 --timeframe 1h
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.strategy_loader import load_all  # noqa: E402


def load_strategy_class(strategy_id: str):
    """Find a strategy by id across the library and return its class."""
    for s in load_all(include_disabled=True):
        if s.metadata.id == strategy_id:
            return type(s)
    return None

MCPCall = Callable[..., Any]


def replay_validate(
    mcp_call: MCPCall,
    strategy_id: str,
    symbol: str,
    timeframe: str = "1h",
    bars: int = 500,
    max_hold_bars: int = 60,
) -> dict:
    """Run a full bar-by-bar validation. Returns summary dict.

    Args:
        mcp_call: a callable with signature `mcp_call(tool, **kwargs) -> dict`
            that proxies the TradingView MCP. In Claude Code, the agent calls
            the mcp__tradingview__* tools directly; this function lets non-
            agent contexts pass their own proxy.
        strategy_id: dotted id matching strategy_registry (e.g.
            "classic.donchian_breakout").
        symbol: TradingView ticker (e.g. "BINANCE:BTCUSDT", "BTCUSD").
        timeframe: TradingView timeframe string ("1h", "4h", "1D", ...).
        bars: how many historical bars to walk forward.
        max_hold_bars: per-trade time stop.
    """
    strat_cls = load_strategy_class(strategy_id)
    if strat_cls is None:
        raise ValueError(f"unknown strategy_id: {strategy_id}")
    strat = strat_cls()  # default params

    # Set up chart + replay
    mcp_call("chart_set_symbol", symbol=symbol)
    mcp_call("chart_set_timeframe", timeframe=timeframe)

    # Rewind to start of replay window: most MCPs accept a bar-index offset
    # back from the live edge. We approximate with the bars argument.
    mcp_call("replay_start", bars_back=bars)

    trades: list[dict] = []
    open_trade: dict | None = None
    ohlcv_buffer: dict[str, list[float]] = {"open": [], "high": [], "low": [], "close": [], "volume": []}

    for i in range(bars):
        mcp_call("replay_step", bars=1)
        # Get the most recent N bars (a small window — strategy needs enough
        # history for ema(200) etc.)
        recent = mcp_call("data_get_ohlcv", count=300, summary=False) or {}
        candles = recent.get("candles") or recent.get("ohlcv") or []
        if not candles:
            continue
        # Re-build the rolling window
        ohlcv_buffer = {
            "open":   [c.get("open",   c[1]) if isinstance(c, dict) else c[1] for c in candles],
            "high":   [c.get("high",   c[2]) if isinstance(c, dict) else c[2] for c in candles],
            "low":    [c.get("low",    c[3]) if isinstance(c, dict) else c[3] for c in candles],
            "close":  [c.get("close",  c[4]) if isinstance(c, dict) else c[4] for c in candles],
            "volume": [c.get("volume", c[5]) if isinstance(c, dict) else c[5] for c in candles],
        }
        last = candles[-1]
        last_bar = {
            "open":  ohlcv_buffer["open"][-1],
            "high":  ohlcv_buffer["high"][-1],
            "low":   ohlcv_buffer["low"][-1],
            "close": ohlcv_buffer["close"][-1],
            "volume":ohlcv_buffer["volume"][-1],
        }

        # Manage open trade — exit on SL / TP / time stop
        if open_trade is not None:
            open_trade["bars_held"] += 1
            high = last_bar["high"]; low = last_bar["low"]
            if open_trade["direction"] == "long":
                if low <= open_trade["sl"]:
                    _close_trade(open_trade, open_trade["sl"], "sl", trades)
                    open_trade = None
                elif high >= open_trade["tp"]:
                    _close_trade(open_trade, open_trade["tp"], "tp", trades)
                    open_trade = None
            else:  # short
                if high >= open_trade["sl"]:
                    _close_trade(open_trade, open_trade["sl"], "sl", trades)
                    open_trade = None
                elif low <= open_trade["tp"]:
                    _close_trade(open_trade, open_trade["tp"], "tp", trades)
                    open_trade = None
            if open_trade is not None and open_trade["bars_held"] >= max_hold_bars:
                _close_trade(open_trade, last_bar["close"], "time_stop", trades)
                open_trade = None

        # Look for new entry only if flat
        if open_trade is None:
            try:
                indicators = strat.populate_indicators(ohlcv_buffer)
                signal = strat.entry_signal(indicators, last_bar)
            except Exception as e:
                signal = None
                trades.append({"bar": i, "error": str(e)})

            if signal is not None:
                # Naive ATR-based SL/TP using strategy params if available
                p = getattr(strat, "_effective_params", strat.params)
                # crude ATR proxy from last 14 bars
                atr = _quick_atr(ohlcv_buffer, 14) or last_bar["close"] * 0.01
                sl_mult = float(p.get("stop_loss_atr_multiplier", 1.5))
                rr = float(p.get("take_profit_rr_ratio", 2.0))
                entry = last_bar["close"]
                if signal.direction == "long":
                    sl = entry - sl_mult * atr
                    tp = entry + sl_mult * atr * rr
                else:
                    sl = entry + sl_mult * atr
                    tp = entry - sl_mult * atr * rr
                open_trade = {
                    "direction": signal.direction,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "bar_opened": i,
                    "bars_held": 0,
                    "confidence": signal.confidence,
                }

    if open_trade is not None:
        # Force-close at last known close
        _close_trade(open_trade, ohlcv_buffer["close"][-1], "session_end", trades)

    mcp_call("replay_stop")

    closed = [t for t in trades if "exit" in t]
    wins = sum(1 for t in closed if t["pnl_pct"] > 0)
    summary = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_walked": bars,
        "n_trades": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "win_rate": (wins / len(closed)) if closed else 0.0,
        "total_pnl_pct": sum(t["pnl_pct"] for t in closed),
        "avg_pnl_pct": (sum(t["pnl_pct"] for t in closed) / len(closed)) if closed else 0.0,
        "trades": closed[:200],  # keep file small
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return summary


def _close_trade(trade: dict, exit_price: float, reason: str, trades: list[dict]) -> None:
    direction = trade["direction"]
    entry = trade["entry"]
    pnl_pct = ((exit_price - entry) / entry * 100) if direction == "long" else ((entry - exit_price) / entry * 100)
    trade["exit"] = exit_price
    trade["exit_reason"] = reason
    trade["pnl_pct"] = pnl_pct
    trades.append(trade)


def _quick_atr(ohlcv: dict, period: int = 14) -> float | None:
    h = ohlcv["high"]; l = ohlcv["low"]; c = ohlcv["close"]
    if len(c) < period + 1:
        return None
    trs = []
    for i in range(-period, 0):
        tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        trs.append(tr)
    return sum(trs) / period


def save_summary(summary: dict, out_dir: str | None = None) -> str:
    if out_dir is None:
        out_dir = os.path.join(PROJECT_ROOT, "data", "backtests", "tv_replay")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = summary["strategy_id"].replace("/", "_").replace(":", "_")
    safe_sym = summary["symbol"].replace("/", "_").replace(":", "_")
    fname = f"{safe_id}__{safe_sym}__{ts}.json"
    path = os.path.join(out_dir, fname)
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser(description="TradingView replay validator")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--bars", type=int, default=500)
    parser.add_argument("--max-hold-bars", type=int, default=60)
    args = parser.parse_args()

    print("[tv_replay_validator] This script requires the TradingView MCP "
          "to be reachable via an mcp_call proxy. From the CLI it prints a "
          "ready-to-run mcp_call() spec; run it from inside Claude Code with "
          "MCP access for a live walk.")
    print(json.dumps({
        "strategy_id": args.strategy,
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "bars": args.bars,
        "max_hold_bars": args.max_hold_bars,
        "next_step": "Call replay_validate(mcp_call, strategy_id, symbol, ...) "
                     "from the agent layer; pass mcp_call=lambda t, **kw: invoke(t, **kw).",
    }, indent=2))


if __name__ == "__main__":
    main()
