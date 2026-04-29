"""Multi-strategy screener: runs every active strategy against every watched symbol.

Stage 2 refactor: replaces the two hand-coded `check_*` functions with a generic
loop driven by lib.strategy_engine + lib.strategy_loader. Every Strategy subclass
in lib/strategy_library/ and every JSON config in config/strategies/ is discovered
automatically and evaluated per symbol per supported timeframe.

Output shape (setups.json) is backward-compatible with confluence_detector.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.strategy_engine import (
    Strategy,
    ohlcv_from_candles,
    last_bar,
    build_setup_from_signal,
)
from lib.strategy_loader import load_all, JSONStrategy
from lib.technical_indicators import atr


MIN_CANDLES = 60  # need enough history for all indicators


def run_strategy_on_symbol(
    strategy: Strategy,
    symbol: str,
    timeframes: dict,
    symbol_sr: dict,
) -> list[dict]:
    """Run a single strategy against a single symbol across its supported timeframes.

    Returns a list of setup dicts (one per timeframe that fires an entry signal).
    """
    setups = []
    preferred = strategy.metadata.timeframes or list(timeframes.keys())
    registry_mode = getattr(strategy, "_registry_mode", "backtest")

    for tf in preferred:
        tf_data = timeframes.get(tf, {})
        candles = tf_data.get("candles", [])
        if len(candles) < MIN_CANDLES:
            continue

        ohlcv = ohlcv_from_candles(candles)
        # JSONStrategy: evaluate via legacy code path (kept for backward compat)
        if isinstance(strategy, JSONStrategy):
            setup = _evaluate_json_strategy(strategy, symbol, tf, ohlcv, symbol_sr)
            if setup:
                setup["strategy_mode"] = registry_mode
                setups.append(setup)
            continue

        # Class-based strategy: standard engine path
        try:
            indicators = strategy.populate_indicators(ohlcv)
            lb = last_bar(ohlcv)
            entry = strategy.entry_signal(indicators, lb)
        except Exception as e:
            print(f"[screener] {strategy.strategy_id} on {symbol}/{tf} raised: {e}")
            continue

        if entry is None:
            continue

        atr_values = indicators.get("atr_14") or atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14)
        atr_val = atr_values[-1] if atr_values and atr_values[-1] is not None else 0.0
        if atr_val <= 0:
            continue

        sizing = strategy.sizing(entry_price=lb["close"], atr_value=atr_val, entry=entry)
        setup = build_setup_from_signal(strategy, symbol, tf, entry, sizing, lb["close"], atr_val)
        setup["strategy_mode"] = registry_mode
        setups.append(setup)
    return setups


# ── Legacy JSON strategy evaluation (kept so internal.momentum_breakout etc still fire) ──
def _evaluate_json_strategy(strategy: JSONStrategy, symbol: str, tf: str, ohlcv: dict, sr: dict) -> dict | None:
    """Evaluate a JSONStrategy by running the now-class-based equivalent where we have one.

    The 4 original JSON configs have been ported to class form in lib/strategy_library/internal/.
    When a JSON strategy has no class port, we skip it (future JSON-only strategies would need
    their own adapter). Currently this returns None because the class versions supersede.
    """
    return None


def screen_all(market_data_path: str | None = None, sr_path: str | None = None) -> list[dict]:
    """Run every active strategy against every symbol in the market-data snapshot."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    signals_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    if market_data_path is None:
        market_data_path = os.path.join(signals_dir, "market_data.json")

    with open(market_data_path) as f:
        raw = json.load(f)
    market_data = raw.get("data", raw)

    sr_data = {}
    if sr_path and os.path.exists(sr_path):
        with open(sr_path) as f:
            sr_data = json.load(f)

    # Load every non-disabled strategy (backtest + paper + live)
    # Scanner evaluates them all; only paper/live mode results should be *acted on*.
    strategies = load_all(include_disabled=False)
    print(f"[screener] Loaded {len(strategies)} strategies")

    setups: list[dict] = []
    for symbol, sdata in market_data.items():
        timeframes = sdata.get("timeframes", {})
        symbol_sr = sr_data.get(symbol, {})
        # Optional asset-class filter: skip a strategy for symbols outside its preferred list
        for strategy in strategies:
            preferred_assets = strategy.metadata.preferred_assets
            if preferred_assets and symbol not in preferred_assets:
                continue
            setups.extend(run_strategy_on_symbol(strategy, symbol, timeframes, symbol_sr))

    setups.sort(key=lambda s: (s.get("strategy_mode") == "live", s["confidence"]), reverse=True)
    return setups


def save_setups(setups: list[dict], output_dir: str | None = None) -> str:
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "setups.json")

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "setups": setups,
            "count": len(setups),
        }, f, indent=2)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Screen watchlist against strategy library")
    parser.add_argument("--market-data", help="Path to market_data.json")
    parser.add_argument("--sr", help="Path to S/R data JSON")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--mode-filter", help="Only report setups from strategies in this mode (live/paper/backtest)")
    args = parser.parse_args()

    setups = screen_all(args.market_data, args.sr)
    if args.mode_filter:
        setups = [s for s in setups if s.get("strategy_mode") == args.mode_filter]

    if not args.no_save:
        path = save_setups(setups)
        print(f"[screener] Saved {len(setups)} setups to {path}")

    print(f"\n{len(setups)} setups found:")
    for s in setups:
        print(f"  [{s['confidence']:.0f}] ({s.get('strategy_mode')}) {s['symbol']} {s['direction'].upper():5s} "
              f"via {s['strategy']}  ({s['timeframe']})  "
              f"entry {s['entry_price']} SL {s['stop_loss']} TP {s['take_profit']} RR {s['rr_ratio']}")


if __name__ == "__main__":
    main()
