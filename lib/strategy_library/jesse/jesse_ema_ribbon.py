"""EMA Ribbon — six-EMA ribbon expansion as trend signal.

Pattern origin: Daryl Guppy "Multiple Moving Averages" (GMMA simplified).
Source URL:     https://github.com/jesse-ai/jesse (community strategy patterns)
License:        MIT
Notes:          Original GMMA uses 12 EMAs; we use 6 short + EMA200 trend filter.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class JesseEmaRibbon(Strategy):
    metadata = StrategyMetadata(
        id="jesse.ema_ribbon",
        name="EMA Ribbon Expansion",
        description="6 EMAs strictly aligned + spreading; long on bull alignment, short on bear.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Late-stage trend; weakest signal during compression.",
    )
    params = {
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        c = ohlcv["close"]
        return {
            "e3": ema(c, 3),
            "e5": ema(c, 5),
            "e8": ema(c, 8),
            "e13": ema(c, 13),
            "e21": ema(c, 21),
            "e34": ema(c, 34),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        keys = ["e3", "e5", "e8", "e13", "e21", "e34"]
        vals = [indicators[k][-1] for k in keys]
        prev = [indicators[k][-2] if len(indicators[k]) >= 2 else None for k in keys]
        if any(v is None for v in vals) or any(v is None for v in prev):
            return None
        # Strictly descending = bull (fast > slow); ascending = bear
        is_bull = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
        is_bear = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
        # Expansion: distance e3-e34 increased
        cur_spread = vals[0] - vals[-1]
        prev_spread = prev[0] - prev[-1]
        if is_bull and cur_spread > prev_spread:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["bull ribbon + expanding"],
                               tags=["trend_follow", "ribbon"])
        if is_bear and cur_spread < prev_spread:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["bear ribbon + expanding"],
                               tags=["trend_follow", "ribbon"])
        return None
