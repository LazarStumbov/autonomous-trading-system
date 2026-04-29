"""Inside Bar Break — breakout of inside-bar pattern.

Pattern origin: Al Brooks, "Reading Price Charts Bar by Bar".
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class InsideBarBreak(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.inside_bar_break",
        name="Inside Bar Breakout",
        description="Inside bar (high<prev high, low>prev low) then break in trend direction.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Tight stop possible (mother bar low/high).",
    )
    params = {
        "trend_period": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "trend_period": [20, 100],
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
        highs = indicators["highs"]
        lows = indicators["lows"]
        et = indicators["ema_trend"][-1]
        if et is None or len(highs) < 3:
            return None
        # bar -2 is inside bar -3? Check inside-bar formed at index -2
        mother_high = highs[-3]
        mother_low = lows[-3]
        inside_high = highs[-2]
        inside_low = lows[-2]
        if not (inside_high < mother_high and inside_low > mother_low):
            return None
        price = last_bar["close"]
        if price > inside_high and price > et:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["inside-bar break up", "above EMA trend"],
                               tags=["price_action", "breakout"])
        if price < inside_low and price < et:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["inside-bar break down", "below EMA trend"],
                               tags=["price_action", "breakout"])
        return None
