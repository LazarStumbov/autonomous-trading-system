"""Momentum Breakout — the original internal strategy, ported to class form.

Source:          internal (Stage 1)
Original config: config/strategies/momentum_breakout.json
License:         MIT (project's own)

Thesis: enter on confirmed breakout above short/medium EMAs with RSI momentum
room (not yet overbought) and volume confirmation. Ride with trailing stop.
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import ema, rsi, atr, volume_ratio


class MomentumBreakout(Strategy):
    metadata = StrategyMetadata(
        id="internal.momentum_breakout",
        name="Momentum Breakout",
        description="Enter on breakout above EMA20/50 with RSI 50-75 and volume >1.5x avg.",
        source="internal",
        version="2.0.0",
        timeframes=["15m", "1h", "4h"],
        asset_classes=["crypto_perp"],
        preferred_assets=["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"],
        risk_notes="Needs trend; avoid in choppy regimes. 3x leverage default, 7x max.",
    )

    params = {
        "rsi_low": 50.0,
        "rsi_high": 75.0,
        "volume_multiplier": 1.5,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "rsi_low": [40.0, 60.0],
        "rsi_high": [65.0, 85.0],
        "volume_multiplier": [1.0, 3.0],
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [1.5, 5.0],
        "default_leverage": [1.0, 7.0],
        "risk_pct": [0.5, 2.0],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        closes = ohlcv["close"]
        highs = ohlcv["high"]
        lows = ohlcv["low"]
        volumes = ohlcv["volume"]
        return {
            "ema_20": ema(closes, 20),
            "ema_50": ema(closes, 50),
            "rsi_14": rsi(closes, 14),
            "atr_14": atr(highs, lows, closes, 14),
            "vol_ratio": volume_ratio(volumes, 20),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        price = last_bar["close"]
        ema20 = indicators["ema_20"][-1]
        ema50 = indicators["ema_50"][-1]
        r = indicators["rsi_14"][-1]
        vr = indicators["vol_ratio"]

        if None in (ema20, ema50, r):
            return None

        reasons = []
        if price > ema20:
            reasons.append("price > EMA20")
        else:
            return None
        if price > ema50:
            reasons.append("price > EMA50")
        else:
            return None
        if p["rsi_low"] <= r <= p["rsi_high"]:
            reasons.append(f"RSI {r:.1f} in [{p['rsi_low']}, {p['rsi_high']}]")
        else:
            return None
        if vr >= p["volume_multiplier"]:
            reasons.append(f"vol {vr:.2f}x >= {p['volume_multiplier']}x")
        else:
            return None

        # Confidence scales with RSI room to overbought + volume excess
        rsi_room = (p["rsi_high"] - r) / (p["rsi_high"] - p["rsi_low"])
        vol_excess = min(1.0, (vr - p["volume_multiplier"]) / p["volume_multiplier"])
        confidence = 60 + 20 * rsi_room + 20 * vol_excess

        return EntrySignal(
            direction="long",
            confidence=min(95.0, max(60.0, confidence)),
            reasons=reasons,
            tags=["momentum", "breakout", "trend_follow"],
        )

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        # Exit early if RSI divergence: price makes new high but RSI lower
        closes = indicators.get("closes") or []
        rsi_series = indicators["rsi_14"]
        if len(rsi_series) < 5 or rsi_series[-1] is None or rsi_series[-4] is None:
            return None
        # Simple divergence heuristic: last RSI < RSI 3 bars ago AND price up
        if rsi_series[-1] < rsi_series[-4] - 5 and last_bar["close"] > open_position.get("entry_price", 0):
            return ExitSignal(reason="rsi_bearish_divergence")
        return None
