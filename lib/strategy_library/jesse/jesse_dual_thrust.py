"""Dual Thrust — N. Kaufman's dual-thrust intraday breakout system.

Pattern origin: Michael Chalek "Dual Thrust" (also Kaufman, "Trading Systems and Methods").
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr


class JesseDualThrust(Strategy):
    metadata = StrategyMetadata(
        id="jesse.dual_thrust",
        name="Dual Thrust Breakout",
        description="Buy if price breaks open + k1 * range; sell if breaks open - k2 * range.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Range computed over N bars; k1=k2 makes it symmetric.",
    )
    params = {
        "lookback": 24,
        "k1": 0.5,
        "k2": 0.5,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [10, 48],
        "k1": [0.2, 1.0],
        "k2": [0.2, 1.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
            "closes": ohlcv["close"],
            "opens": ohlcv["open"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        h = indicators["highs"]
        l = indicators["lows"]
        c = indicators["closes"]
        if len(h) < n + 1:
            return None
        hh = max(h[-n - 1:-1])
        lc = min(c[-n - 1:-1])
        hc = max(c[-n - 1:-1])
        ll = min(l[-n - 1:-1])
        rng = max(hh - lc, hc - ll)
        if rng <= 0:
            return None
        open_price = last_bar["open"]
        upper = open_price + p["k1"] * rng
        lower = open_price - p["k2"] * rng
        price = last_bar["close"]
        if price > upper:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["dual-thrust upper break"],
                               tags=["breakout", "dual_thrust"])
        if price < lower:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["dual-thrust lower break"],
                               tags=["breakout", "dual_thrust"])
        return None
