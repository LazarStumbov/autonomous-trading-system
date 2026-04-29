"""Opening Range Breakout — break of first N bars' range.

Pattern origin: Toby Crabel "Day Trading with Short Term Price Patterns and Opening Range Breakout" (1990).
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
Notes:          Crypto has no session open; we use a rolling N-bar opening-range proxy.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class LeanOpeningRange(Strategy):
    metadata = StrategyMetadata(
        id="lean.opening_range",
        name="Opening Range Breakout (rolling)",
        description="First N bars define a range; break in trend direction.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Crypto 24/7 makes 'open' arbitrary; rolling proxy used.",
    )
    params = {
        "or_bars": 6,
        "trend_period": 50,
        "min_volume_ratio": 1.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "or_bars": [3, 12],
        "trend_period": [20, 100],
        "min_volume_ratio": [0.7, 2.5],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "ema_trend": ema(ohlcv["close"], int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["or_bars"])
        h = indicators["highs"]
        l = indicators["lows"]
        et = indicators["ema_trend"][-1]
        if len(h) < n + 2 or et is None:
            return None
        # Range from bars [-(n+1) .. -2] (inclusive); current bar -1 is the break candidate
        or_high = max(h[-n - 1:-1])
        or_low = min(l[-n - 1:-1])
        price = last_bar["close"]
        if price > or_high and price > et:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=[f"break of {n}-bar opening high"],
                               tags=["breakout", "opening_range"])
        if price < or_low and price < et:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=[f"break of {n}-bar opening low"],
                               tags=["breakout", "opening_range"])
        return None
