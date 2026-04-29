"""Turtle System #2 — 55-bar entry, 20-bar exit (Richard Dennis / Curtis Faith).

Pattern origin:  Original Turtle Trader rules (Curtis Faith, "Way of the Turtle").
                 System #2 is the slower variant: 55-bar Donchian breakout entry,
                 20-bar opposite-channel exit. Public domain.
License:         MIT (our impl).
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import donchian, atr


class TurtleSystem2(Strategy):
    metadata = StrategyMetadata(
        id="classic.turtle_system2_55_20",
        name="Turtle System #2 (55/20)",
        description="Slow Turtle: 55-bar entry, 20-bar trailing exit.",
        source="classic",
        source_url="https://en.wikipedia.org/wiki/Turtle_trading",
        license="MIT",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Slow trend-follower; many small losses, occasional big wins.",
    )
    params = {
        "entry_period": 55,
        "exit_period": 20,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 4.0,
        "default_leverage": 2.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "entry_period": [40, 80],
        "exit_period": [10, 30],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.5, 6.0],
        "default_leverage": [1.0, 3.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "entry": donchian(ohlcv["high"], ohlcv["low"], int(p["entry_period"])),
            "exit": donchian(ohlcv["high"], ohlcv["low"], int(p["exit_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        u = indicators["entry"]["upper"]; l = indicators["entry"]["lower"]
        if len(u) < 2 or u[-2] is None or l[-2] is None:
            return None
        c = last_bar["close"]
        if c > u[-2]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=[f"close > {int(self._effective_params['entry_period'])}-bar high (slow turtle)"],
                               tags=["breakout", "trend_follow", "turtle"])
        if c < l[-2]:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=[f"close < {int(self._effective_params['entry_period'])}-bar low (slow turtle)"],
                               tags=["breakout", "trend_follow", "turtle"])
        return None

    def exit_signal(self, indicators, last_bar, open_position) -> Optional[ExitSignal]:
        u = indicators["exit"]["upper"]; l = indicators["exit"]["lower"]
        if u[-2] is None or l[-2] is None:
            return None
        c = last_bar["close"]
        d = open_position.get("direction")
        if d == "long" and c < l[-2]:
            return ExitSignal(reason="turtle_exit_break_down")
        if d == "short" and c > u[-2]:
            return ExitSignal(reason="turtle_exit_break_up")
        return None
