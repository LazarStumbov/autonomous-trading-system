"""Pivot Bounce — bounce off rolling pivot levels.

Pattern origin: classic floor-trader pivot points (Person, "A Complete Guide to Technical Trading Tactics").
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class JessePivotBounce(Strategy):
    metadata = StrategyMetadata(
        id="jesse.pivot_bounce",
        name="Rolling Pivot Bounce",
        description="Long bounce from S1 in uptrend; short rejection from R1 in downtrend.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Levels recalculated each bar from rolling 24-bar HLC.",
    )
    params = {
        "pivot_lookback": 24,
        "trend_period": 50,
        "tolerance_pct": 0.3,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "pivot_lookback": [12, 48],
        "trend_period": [20, 100],
        "tolerance_pct": [0.1, 1.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
            "closes": c,
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["pivot_lookback"])
        h = indicators["highs"]
        l = indicators["lows"]
        c = indicators["closes"]
        et = indicators["ema_trend"][-1]
        if len(h) < n + 1 or et is None:
            return None
        # Pivot from previous N bars
        ph = max(h[-n - 1:-1])
        pl = min(l[-n - 1:-1])
        pc = c[-2]
        pivot = (ph + pl + pc) / 3
        r1 = 2 * pivot - pl
        s1 = 2 * pivot - ph
        price = last_bar["close"]
        low = last_bar["low"]
        high = last_bar["high"]
        tol = p["tolerance_pct"] / 100
        # Bounce off S1 in uptrend
        if price > et and abs(low - s1) / s1 <= tol and price > low:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=["bounce off S1", "uptrend"],
                               tags=["mean_reversion", "pivot"])
        if price < et and abs(high - r1) / r1 <= tol and price < high:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["rejection at R1", "downtrend"],
                               tags=["mean_reversion", "pivot"])
        return None
