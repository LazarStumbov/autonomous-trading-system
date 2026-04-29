"""Map TradingView indicator strings onto our internal signal-type taxonomy.

This is the bridge: a TV alert saying "RSI oversold" gets tagged as
signal_type='mean_reversion' so confluence_detector.py can weight it like
our native RSI-based strategies.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

INDICATOR_TO_TYPE = {
    "rsi": "mean_reversion",
    "bollinger": "mean_reversion",
    "bb ": "mean_reversion",
    "vwap": "mean_reversion",
    "macd": "momentum",
    "ema cross": "momentum",
    "ema crossover": "momentum",
    "donchian": "breakout",
    "breakout": "breakout",
    "supertrend": "trend_follow",
    "ichimoku": "trend_follow",
    "divergence": "reversal",
    "fvg": "structure",
    "order block": "structure",
    "liquidity": "structure",
}


def map_indicator(text: str) -> str:
    t = (text or "").lower()
    for key, typ in INDICATOR_TO_TYPE.items():
        if key in t:
            return typ
    return "tv_generic"


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
    print(f"[indicator_mapper] {setup['symbol']} indicator='{setup.get('indicator')}' → signal_type='{setup['signal_type']}'")


if __name__ == "__main__":
    main()
