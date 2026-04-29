"""Volatility Targeting — enter when realized vol contracts below threshold.

Pattern origin: Mebane Faber's "Tactical Asset Allocation" + AQR vol-targeting research.
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, sma, ema


class LeanVolatilityTargeting(Strategy):
    metadata = StrategyMetadata(
        id="lean.volatility_targeting",
        name="Volatility Contraction Entry",
        description="Realized vol < median(vol, 50). Enter on first up-bar in trend direction.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Low vol = better R:R but slower fills; combine with breakout.",
    )
    params = {
        "vol_window": 20,
        "median_lookback": 50,
        "trend_period": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "vol_window": [10, 30],
        "median_lookback": [30, 100],
        "trend_period": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        n = int(p["vol_window"])
        # Realized "vol" proxy: stdev of returns over window
        rets = [0.0] + [(c[i] - c[i - 1]) / c[i - 1] if c[i - 1] > 0 else 0.0 for i in range(1, len(c))]
        vol = []
        for i in range(len(c)):
            if i < n:
                vol.append(None)
            else:
                w = rets[i - n + 1:i + 1]
                m = sum(w) / n
                var = sum((x - m) ** 2 for x in w) / n
                vol.append(var ** 0.5)
        return {
            "vol": vol,
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["median_lookback"])
        v = indicators["vol"]
        et = indicators["ema_trend"][-1]
        if len(v) < n + 1 or v[-1] is None or et is None:
            return None
        recent = sorted([x for x in v[-n - 1:-1] if x is not None])
        if not recent:
            return None
        median = recent[len(recent) // 2]
        if v[-1] >= median:
            return None
        price = last_bar["close"]
        if price > et:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=["vol contraction below median", "uptrend"],
                               tags=["volatility", "low_vol"])
        if price < et:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["vol contraction below median", "downtrend"],
                               tags=["volatility", "low_vol"])
        return None
