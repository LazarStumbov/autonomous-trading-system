"""Pull TradingView indicator values for watchlist symbols across multiple timeframes.

Runs inside the hourly market_scan cron (after screener.py).

Two operating modes:
  MCP mode   — when called from within Claude Code (agent layer passes mcp_call).
               Uses tradingview_bridge.multi_tf_alignment() for TV-native EMA/RSI/ATR.
  Fallback   — when run as a Modal subprocess (no MCP).
               Uses ccxt OHLCV + ta-lib for the same EMA stack / RSI calculation.

Either way the output is `data/signals/<date>/tv_pull.json`, which the Phase-1
glob loader in confluence_detector.py picks up automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import SignalType
from lib.tradingview_bridge import multi_tf_alignment

TIMEFRAMES = ["15m", "1h", "4h"]


def _load_watchlist_symbols() -> list[str]:
    cfg = os.path.join(PROJECT_ROOT, "config", "watchlist.json")
    with open(cfg) as f:
        wl = json.load(f)
    # Crypto perps are the most relevant: 24/7, TV covers them natively.
    return list(wl["watchlist"].get("crypto_perpetuals", []))


def _classify_alignment(tf_data: dict) -> dict:
    """Reduce multi-TF trend+momentum flags to a single directional signal."""
    bull = sum(1 for d in tf_data.values() if d.get("trend") == "bull" and d.get("momentum") == "bull")
    bear = sum(1 for d in tf_data.values() if d.get("trend") == "bear" and d.get("momentum") == "bear")
    n = max(len(tf_data), 1)
    if bull >= n * 0.6:
        return {"direction": "long", "confidence": round(bull / n, 2)}
    if bear >= n * 0.6:
        return {"direction": "short", "confidence": round(bear / n, 2)}
    return {"direction": None, "confidence": round(max(bull, bear) / n, 2)}


def _ccxt_fallback(symbol: str) -> Optional[dict]:
    """Compute multi-TF alignment from ccxt OHLCV when MCP is not available."""
    try:
        import pandas as pd
        import ta
    except ImportError:
        print("[tv_pull_scanner] pandas/ta not available — skipping ccxt fallback")
        return None
    try:
        from lib.market_data import get_market_data_provider
        provider = get_market_data_provider()
        tf_data: dict[str, dict] = {}
        for tf in TIMEFRAMES:
            ohlcv = provider.fetch_ohlcv(symbol, tf, limit=250)
            if not ohlcv:
                continue
            df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
            df["ema20"]  = ta.trend.ema_indicator(df["close"], window=20)
            df["ema50"]  = ta.trend.ema_indicator(df["close"], window=50)
            df["ema200"] = ta.trend.ema_indicator(df["close"], window=200)
            df["rsi"]    = ta.momentum.rsi(df["close"], window=14)
            last = df.iloc[-1]
            e20, e50, e200, rsi = float(last.ema20), float(last.ema50), float(last.ema200), float(last.rsi)
            trend = "bull" if e20 > e50 > e200 else "bear" if e20 < e50 < e200 else "mixed"
            momentum = "bull" if rsi > 60 else "bear" if rsi < 40 else "neutral"
            tf_data[tf] = {"trend": trend, "momentum": momentum, "rsi": rsi, "ema20": e20, "ema50": e50, "ema200": e200}
        if not tf_data:
            return None
        return {"symbol": symbol, "timeframes": tf_data, "source": "ccxt_fallback"}
    except Exception as e:
        print(f"[tv_pull_scanner] ccxt fallback failed for {symbol}: {e}")
        return None


def run_scan(
    mcp_call: Optional[Callable] = None,
    symbols: Optional[list[str]] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Run the pull scan. Returns path to written tv_pull.json."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if symbols is None:
        try:
            symbols = _load_watchlist_symbols()
        except Exception as e:
            print(f"[tv_pull_scanner] could not load watchlist: {e}")
            symbols = []

    signals: list[dict] = []
    for symbol in symbols:
        try:
            if mcp_call is not None:
                data = multi_tf_alignment(mcp_call, symbol, timeframes=TIMEFRAMES)
                data["source"] = "tradingview_mcp"
            else:
                data = _ccxt_fallback(symbol)
                if data is None:
                    continue

            alignment = _classify_alignment(data.get("timeframes", {}))
            if alignment["direction"] is None:
                continue

            signals.append({
                "symbol": symbol,
                "direction": alignment["direction"],
                "signal_type": SignalType.TECHNICAL_BREAKOUT.value,
                "confidence": alignment["confidence"],
                "source": data.get("source", "tradingview"),
                "timeframes": data.get("timeframes", {}),
            })
        except Exception as e:
            print(f"[tv_pull_scanner] {symbol}: {e}")

    out_path = os.path.join(output_dir, "tv_pull.json")
    with open(out_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols_scanned": len(symbols),
            "signals": signals,
        }, f, indent=2)

    print(f"[tv_pull_scanner] {len(signals)} directional signals from {len(symbols)} symbols → {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="TV pull scanner — multi-TF alignment for watchlist")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--symbols", nargs="+", help="Override symbol list")
    args = parser.parse_args()
    run_scan(mcp_call=None, symbols=args.symbols, output_dir=args.output_dir)


if __name__ == "__main__":
    main()