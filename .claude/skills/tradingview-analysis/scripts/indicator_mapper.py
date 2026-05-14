"""Map TradingView indicator strings onto our internal signal-type taxonomy.

This is the bridge: a TV alert saying "RSI oversold" gets tagged as
SignalType.MEAN_REVERSION so confluence_detector.py can weight it alongside
our native RSI-based strategies.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import SignalType

# Keyword → SignalType. Checked in order; first match wins.
INDICATOR_TO_TYPE: dict[str, SignalType] = {
    "rsi": SignalType.MEAN_REVERSION,
    "bollinger": SignalType.MEAN_REVERSION,
    "bb ": SignalType.MEAN_REVERSION,
    "vwap": SignalType.MEAN_REVERSION,
    "divergence": SignalType.MEAN_REVERSION,
    "macd": SignalType.TECHNICAL_BREAKOUT,
    "ema cross": SignalType.TECHNICAL_BREAKOUT,
    "ema crossover": SignalType.TECHNICAL_BREAKOUT,
    "donchian": SignalType.TECHNICAL_BREAKOUT,
    "breakout": SignalType.TECHNICAL_BREAKOUT,
    "supertrend": SignalType.TECHNICAL_BREAKOUT,
    "ichimoku": SignalType.TECHNICAL_BREAKOUT,
    "fvg": SignalType.STRUCTURE_BREAK,
    "order block": SignalType.STRUCTURE_BREAK,
    "liquidity": SignalType.STRUCTURE_BREAK,
    "volume": SignalType.VOLUME_ANOMALY,
    "vol spike": SignalType.VOLUME_ANOMALY,
    "sentiment": SignalType.SENTIMENT_SHIFT,
    "funding": SignalType.TRADER_ACCUMULATION,
    "open interest": SignalType.TRADER_ACCUMULATION,
}


def map_indicator(text: str) -> SignalType:
    t = (text or "").lower()
    for key, typ in INDICATOR_TO_TYPE.items():
        if key in t:
            return typ
    return SignalType.TECHNICAL_BREAKOUT


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path(PROJECT_ROOT) / "data" / "signals" / today / "tv_setup.json"
    if not path.exists():
        print("[indicator_mapper] no tv_setup.json to map")
        return
    with open(path) as f:
        setup = json.load(f)
    setup["signal_type"] = map_indicator(f"{setup.get('indicator','')} {setup.get('message','')}")
    with open(path, "w") as f:
        json.dump(setup, f, indent=2)
    print(f"[indicator_mapper] {setup['symbol']} indicator='{setup.get('indicator')}' → signal_type='{setup['signal_type']}' (enum value)")


if __name__ == "__main__":
    main()
