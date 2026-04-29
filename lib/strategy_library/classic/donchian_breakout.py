"""Donchian channel breakout (the original 'Turtle' pattern).

Pattern origin: Richard Donchian / Turtle Traders (public domain).
License:        MIT (our implementation)

Long on close above highest-high(N); short on close below lowest-low(N).
Aggressive variant uses N=20 for entries and N=10 for exits (classic turtle).
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import donchian, atr


class DonchianBreakout(Strategy):
    metadata = StrategyMetadata(
        id="classic.donchian_breakout_20_10",
        name="Donchian Breakout 20/10",
        description="Enter on 20-bar breakout; exit on 10-bar opposite channel.",
        source="classic",
        source_url="https://en.wikipedia.org/wiki/Donchian_channel",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Many false breakouts in crypto. Use higher timeframes (1h+) to reduce noise.",
    )

    params = {
        "entry_period": 20,
        "exit_period": 10,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 3.0,  # trend-followers aim for R:R 3+
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "entry_period": [10, 55],
        "exit_period": [5, 20],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.0, 6.0],
        "default_leverage": [1.0, 5.0],
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
        # Use previous bar's channel (don't look ahead)
        upper = indicators["entry"]["upper"]
        lower = indicators["entry"]["lower"]
        if len(upper) < 2 or upper[-2] is None or lower[-2] is None:
            return None

        price = last_bar["close"]
        if price > upper[-2]:
            return EntrySignal(
                direction="long",
                confidence=68.0,
                reasons=[f"close > {int(self._effective_params['entry_period'])}-bar high"],
                tags=["breakout", "trend_follow", "turtle"],
            )
        if price < lower[-2]:
            return EntrySignal(
                direction="short",
                confidence=68.0,
                reasons=[f"close < {int(self._effective_params['entry_period'])}-bar low"],
                tags=["breakout", "trend_follow", "turtle"],
            )
        return None

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        # Exit when price breaks opposite N-bar channel
        upper = indicators["exit"]["upper"]
        lower = indicators["exit"]["lower"]
        if upper[-2] is None or lower[-2] is None:
            return None
        price = last_bar["close"]
        direction = open_position.get("direction")
        if direction == "long" and price < lower[-2]:
            return ExitSignal(reason="exit_channel_break_down")
        if direction == "short" and price > upper[-2]:
            return ExitSignal(reason="exit_channel_break_up")
        return None
