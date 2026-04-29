"""ATR Squeeze Break — low volatility + price breakout.

Pattern origin: volatility expansion concept (Tony Crabel "Day Trading with Short Term Price Patterns").
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, donchian


class AtrSqueezeBreak(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.atr_squeeze_break",
        name="ATR Squeeze Breakout",
        description="ATR at multi-bar low + Donchian breakout.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="False breakouts in chop; require ATR squeeze.",
    )
    params = {
        "atr_lookback": 30,
        "channel_period": 20,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "atr_lookback": [10, 60],
        "channel_period": [10, 40],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "channel": donchian(ohlcv["high"], ohlcv["low"], int(p["channel_period"])),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        a = indicators["atr_14"]
        n = int(p["atr_lookback"])
        if len(a) < n + 1 or a[-1] is None:
            return None
        recent_atr = [v for v in a[-n - 1:-1] if v is not None]
        if len(recent_atr) < n // 2:
            return None
        # Squeeze: previous ATR was at minimum of recent N bars
        if a[-2] is None or a[-2] > min(recent_atr):
            return None
        upper = indicators["channel"]["upper"][-2]
        lower = indicators["channel"]["lower"][-2]
        if upper is None or lower is None:
            return None
        price = last_bar["close"]
        if price > upper:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["ATR squeeze + channel break up"],
                               tags=["volatility", "breakout"])
        if price < lower:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["ATR squeeze + channel break down"],
                               tags=["volatility", "breakout"])
        return None
