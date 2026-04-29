"""Supertrend trend-follow — enter on flip, ride until opposite flip.

Pattern origin: Olivier Seban / public TradingView indicator (pattern in public domain).
License:        MIT (our implementation)

Supertrend is an ATR-based trend indicator that outputs +1 (long) or -1 (short).
We enter on trend flip and exit on next flip. Aggressive short-timeframe strategy.
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import supertrend, atr


class SupertrendFollow(Strategy):
    metadata = StrategyMetadata(
        id="classic.supertrend_follow_10_3",
        name="Supertrend Follow (10, 3.0)",
        description="Enter on Supertrend flip, exit on opposite flip.",
        source="classic",
        source_url="https://www.tradingview.com/support/solutions/43000634738-supertrend/",
        license="MIT",
        version="1.0.0",
        timeframes=["5m", "15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Good in trends, painful in chop. Add confluence filter (volume / trend higher-TF).",
    )

    params = {
        "period": 10,
        "multiplier": 3.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "period": [7, 21],
        "multiplier": [2.0, 5.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        st = supertrend(ohlcv["high"], ohlcv["low"], ohlcv["close"], int(p["period"]), p["multiplier"])
        return {
            "supertrend": st,
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        trend = indicators["supertrend"]["trend"]
        if len(trend) < 2:
            return None
        # Detect flip
        if trend[-2] == -1 and trend[-1] == 1:
            return EntrySignal(
                direction="long",
                confidence=70.0,
                reasons=["Supertrend flipped to +1"],
                tags=["trend_follow", "supertrend"],
            )
        if trend[-2] == 1 and trend[-1] == -1:
            return EntrySignal(
                direction="short",
                confidence=70.0,
                reasons=["Supertrend flipped to -1"],
                tags=["trend_follow", "supertrend"],
            )
        return None

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        trend = indicators["supertrend"]["trend"]
        direction = open_position.get("direction")
        if direction == "long" and trend[-1] == -1:
            return ExitSignal(reason="supertrend_flip_bearish")
        if direction == "short" and trend[-1] == 1:
            return ExitSignal(reason="supertrend_flip_bullish")
        return None
