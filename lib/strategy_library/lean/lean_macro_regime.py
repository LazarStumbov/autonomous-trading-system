"""Macro Regime — trade only when EMA-slope and trend agree (regime filter).

Pattern origin: Andrew Lo's adaptive markets hypothesis applied as regime filter.
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, rsi


class LeanMacroRegime(Strategy):
    metadata = StrategyMetadata(
        id="lean.macro_regime",
        name="Macro Regime Trend",
        description="EMA200 slope > 0 AND price > EMA50 AND RSI 50-65 = entrenched bull regime.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Selective; few signals but high quality.",
    )
    params = {
        "slope_lookback": 20,
        "min_slope_pct": 0.5,
        "rsi_low": 50.0,
        "rsi_high": 65.0,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 3.5,
        "default_leverage": 2.5,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "slope_lookback": [10, 50],
        "min_slope_pct": [0.1, 2.0],
        "rsi_low": [40.0, 55.0],
        "rsi_high": [60.0, 75.0],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 4.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        c = ohlcv["close"]
        return {
            "ema_50": ema(c, 50),
            "ema_200": ema(c, 200),
            "rsi": rsi(c, 14),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["slope_lookback"])
        e200 = indicators["ema_200"]
        e50 = indicators["ema_50"][-1]
        r = indicators["rsi"][-1]
        if len(e200) < n + 1 or e200[-1] is None or e200[-n - 1] is None or e50 is None or r is None:
            return None
        slope = (e200[-1] - e200[-n - 1]) / e200[-n - 1] * 100
        price = last_bar["close"]
        if slope >= p["min_slope_pct"] and price > e50 and p["rsi_low"] <= r <= p["rsi_high"]:
            return EntrySignal(direction="long", confidence=74.0,
                               reasons=[f"EMA200 slope +{slope:.2f}%", "above EMA50", f"RSI {r:.1f}"],
                               tags=["regime", "macro_trend"])
        if slope <= -p["min_slope_pct"] and price < e50 and (100 - p["rsi_high"]) <= r <= (100 - p["rsi_low"]):
            return EntrySignal(direction="short", confidence=72.0,
                               reasons=[f"EMA200 slope {slope:.2f}%", "below EMA50", f"RSI {r:.1f}"],
                               tags=["regime", "macro_trend"])
        return None
