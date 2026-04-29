"""Parse a TradingView alert JSON into a normalized setup dict.

Expected payload shape (webhook sends raw JSON):
    {"symbol": "BTCUSDT", "direction": "long", "timeframe": "15m",
     "indicator": "RSI oversold", "entry": 50000, "sl": 49000, "tp": 52000, ...}

Writes data/signals/<date>/tv_setup.json so confluence_detector can include it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


DIRECTION_MAP = {"buy": "long", "long": "long", "sell": "short", "short": "short"}


def normalize_symbol(sym: str) -> str:
    """Convert Bybit-style 'BTCUSDT' to ccxt perp format 'BTC/USDT:USDT'."""
    s = (sym or "").upper().replace(" ", "")
    if "/" in s:
        return s
    if s.endswith("USDT"):
        return f"{s[:-4]}/USDT:USDT"
    if s.endswith("USDC"):
        return f"{s[:-4]}/USDC:USDC"
    return s


def parse_alert(raw: dict) -> dict:
    symbol = normalize_symbol(raw.get("symbol") or raw.get("ticker") or "")
    direction = DIRECTION_MAP.get(str(raw.get("direction") or raw.get("side") or "").lower(), "long")
    return {
        "source": "tradingview",
        "symbol": symbol,
        "direction": direction,
        "timeframe": raw.get("timeframe") or raw.get("interval") or "15m",
        "indicator": raw.get("indicator") or raw.get("strategy") or "tv_alert",
        "entry_price": float(raw.get("entry") or raw.get("price") or 0) or None,
        "stop_loss": float(raw.get("sl") or raw.get("stop_loss") or 0) or None,
        "take_profit": float(raw.get("tp") or raw.get("take_profit") or 0) or None,
        "confidence": float(raw.get("confidence") or 60),
        "message": raw.get("message") or raw.get("description") or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw": raw,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to raw TV alert JSON")
    args = parser.parse_args()

    with open(args.input) as f:
        raw = json.load(f)

    parsed = parse_alert(raw)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "tv_setup.json"
    with open(out, "w") as f:
        json.dump(parsed, f, indent=2)
    print(f"[alert_parser] parsed: {parsed['symbol']} {parsed['direction']} from '{parsed['indicator']}' → {out}")


if __name__ == "__main__":
    main()
