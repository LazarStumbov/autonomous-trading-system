"""Donchian-50 Slow Trend — longer-period turtle variant.

Pattern origin: Richard Dennis original Turtle System 2 (55-bar entry).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import donchian, atr


class Donchian50(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.donchian_50",
        name="Donchian 50 Slow Turtle",
        description="50-bar entry, 20-bar exit. Long-horizon trend.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Slow signal, fewer trades, larger drawdowns possible.",
    )
    params = {
        "entry_period": 50,
        "exit_period": 20,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 4.0,
        "default_leverage": 2.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "entry_period": [40, 80],
        "exit_period": [10, 30],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.5, 6.0],
        "default_leverage": [1.0, 4.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "entry": donchian(ohlcv["high"], ohlcv["low"], int(p["entry_period"])),
            "exit": donchian(ohlcv["high"], ohlcv["low"], int(p["exit_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        u = indicators["entry"]["upper"]
        l = indicators["entry"]["lower"]
        if len(u) < 2 or u[-2] is None or l[-2] is None:
            return None
        price = last_bar["close"]
        if price > u[-2]:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["50-bar high broken"], tags=["breakout", "turtle_2"])
        if price < l[-2]:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["50-bar low broken"], tags=["breakout", "turtle_2"])
        return None

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        u = indicators["exit"]["upper"]
        l = indicators["exit"]["lower"]
        if u[-2] is None or l[-2] is None:
            return None
        price = last_bar["close"]
        d = open_position.get("direction")
        if d == "long" and price < l[-2]:
            return ExitSignal(reason="exit_20_bar_low")
        if d == "short" and price > u[-2]:
            return ExitSignal(reason="exit_20_bar_high")
        return None
