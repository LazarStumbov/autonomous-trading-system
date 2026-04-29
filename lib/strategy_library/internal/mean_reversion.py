"""Mean Reversion — fade extreme moves when price is oversold at lower BB.

Source:          internal (Stage 1)
Original config: config/strategies/mean_reversion.json
License:         MIT
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal, Sizing
from lib.technical_indicators import ema, rsi, bollinger_bands, atr


class MeanReversion(Strategy):
    metadata = StrategyMetadata(
        id="internal.mean_reversion",
        name="Mean Reversion",
        description="Buy oversold RSI at BB lower band, target return to mean (EMA20).",
        source="internal",
        version="2.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        preferred_assets=["BTC/USDT:USDT", "ETH/USDT:USDT"],
        risk_notes="Lower leverage (2x default). Avoid during strong trends or news events.",
    )

    params = {
        "rsi_oversold": 30.0,
        "rsi_overbought": 70.0,
        "bb_period": 20,
        "bb_std": 2.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 2.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "rsi_oversold": [20.0, 40.0],
        "rsi_overbought": [60.0, 80.0],
        "bb_std": [1.5, 3.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        closes = ohlcv["close"]
        highs = ohlcv["high"]
        lows = ohlcv["low"]
        p = self._effective_params
        return {
            "rsi": rsi(closes, 14),
            "ema_20": ema(closes, 20),
            "bb": bollinger_bands(closes, int(p["bb_period"]), p["bb_std"]),
            "atr_14": atr(highs, lows, closes, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        price = last_bar["close"]
        r = indicators["rsi"][-1]
        bb_lower = indicators["bb"]["lower"][-1]
        bb_upper = indicators["bb"]["upper"][-1]

        if None in (r, bb_lower, bb_upper):
            return None

        # Long: oversold + price at or below lower BB
        if r <= p["rsi_oversold"] and price <= bb_lower * 1.01:
            confidence = 60 + (p["rsi_oversold"] - r) * 1.5  # deeper oversold -> more confidence
            return EntrySignal(
                direction="long",
                confidence=min(90.0, max(60.0, confidence)),
                reasons=[f"RSI {r:.1f} oversold", "price at BB lower"],
                tags=["mean_reversion", "oversold"],
            )

        # Short: overbought + price at or above upper BB
        if r >= p["rsi_overbought"] and price >= bb_upper * 0.99:
            confidence = 60 + (r - p["rsi_overbought"]) * 1.5
            return EntrySignal(
                direction="short",
                confidence=min(90.0, max(60.0, confidence)),
                reasons=[f"RSI {r:.1f} overbought", "price at BB upper"],
                tags=["mean_reversion", "overbought"],
            )

        return None

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        # Exit when price returns to EMA20 (the mean)
        ema20 = indicators["ema_20"][-1]
        if ema20 is None:
            return None
        direction = open_position.get("direction")
        entry = open_position.get("entry_price", 0)
        price = last_bar["close"]

        if direction == "long" and price >= ema20 and price > entry:
            return ExitSignal(reason="reverted_to_mean", partial=True, partial_pct=50.0)
        if direction == "short" and price <= ema20 and price < entry:
            return ExitSignal(reason="reverted_to_mean", partial=True, partial_pct=50.0)
        return None
