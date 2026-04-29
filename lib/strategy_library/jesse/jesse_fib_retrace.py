"""Fibonacci Retracement Bounce — buy 0.618 retrace in uptrend.

Pattern origin: Leonardo Pisano (Fibonacci) sequences applied to price (Murphy, Frost & Prechter).
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class JesseFibRetrace(Strategy):
    metadata = StrategyMetadata(
        id="jesse.fib_retrace",
        name="Fibonacci 0.618 Bounce",
        description="In uptrend (EMA100 rising), buy at 0.618 retrace of last swing.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Naive swing-detection (lookback high/low); refined version would use ZigZag.",
    )
    params = {
        "lookback": 30,
        "fib_level": 0.618,
        "tolerance_pct": 0.5,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [15, 60],
        "fib_level": [0.382, 0.786],
        "tolerance_pct": [0.2, 1.5],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        c = ohlcv["close"]
        return {
            "ema_trend": ema(c, 100),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        h = indicators["highs"]
        l = indicators["lows"]
        et = indicators["ema_trend"]
        if len(h) < n + 5 or et[-1] is None or et[-5] is None:
            return None
        swing_h = max(h[-n - 1:-1])
        swing_l = min(l[-n - 1:-1])
        rng = swing_h - swing_l
        if rng <= 0:
            return None
        tol = p["tolerance_pct"] / 100
        price = last_bar["close"]
        # Uptrend: EMA rising
        if et[-1] > et[-5] and l[-1] > l[-5]:
            target = swing_h - rng * p["fib_level"]
            if abs(last_bar["low"] - target) / target <= tol and price > target:
                return EntrySignal(direction="long", confidence=68.0,
                                   reasons=[f"0.{int(p['fib_level']*1000)} retrace bounce"],
                                   tags=["fibonacci", "retrace"])
        if et[-1] < et[-5] and h[-1] < h[-5]:
            target = swing_l + rng * p["fib_level"]
            if abs(last_bar["high"] - target) / target <= tol and price < target:
                return EntrySignal(direction="short", confidence=66.0,
                                   reasons=[f"0.{int(p['fib_level']*1000)} retrace rejection"],
                                   tags=["fibonacci", "retrace"])
        return None
