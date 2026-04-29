"""Chaikin Volatility — high-low range expansion as breakout trigger.

Pattern origin: Marc Chaikin's Volatility indicator.
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class JesseChaikinVolatility(Strategy):
    metadata = StrategyMetadata(
        id="jesse.chaikin_volatility",
        name="Chaikin Volatility Expansion",
        description="EMA(H-L) accelerating + price > EMA20 = expansion long; mirror for short.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Volatility indicators don't direct; pair with trend.",
    )
    params = {
        "vol_period": 10,
        "vol_lookback": 10,
        "min_change_pct": 10.0,
        "trend_period": 20,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "vol_period": [5, 20],
        "vol_lookback": [5, 20],
        "min_change_pct": [3.0, 30.0],
        "trend_period": [10, 50],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        c = ohlcv["close"]
        ranges = [hi - lo for hi, lo in zip(h, l)]
        return {
            "vol_ema": ema(ranges, int(p["vol_period"])),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["vol_lookback"])
        ve = indicators["vol_ema"]
        et = indicators["ema_trend"][-1]
        if len(ve) < n + 1 or ve[-1] is None or ve[-n - 1] is None or et is None:
            return None
        if ve[-n - 1] == 0:
            return None
        change = (ve[-1] - ve[-n - 1]) / ve[-n - 1] * 100
        if change < p["min_change_pct"]:
            return None
        price = last_bar["close"]
        if price > et:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"vol expansion {change:.1f}%", "uptrend"],
                               tags=["volatility"])
        if price < et:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"vol expansion {change:.1f}%", "downtrend"],
                               tags=["volatility"])
        return None
