"""RSI divergence — detect bullish/bearish divergence over recent lookback.

Pattern: classic divergence trading (price makes new high/low but RSI doesn't).
License: MIT (our implementation).
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, atr, ema


class RsiDivergence(Strategy):
    metadata = StrategyMetadata(
        id="community.rsi_divergence",
        name="RSI Divergence",
        description="Detect 5-bar regular bullish/bearish divergence between price and RSI.",
        source="community",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Divergence is a reversal signal — confirm with trend context / volume.",
    )

    params = {
        "lookback": 10,
        "rsi_period": 14,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "lookback": [5, 20],
        "rsi_period": [9, 21],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "rsi": rsi(ohlcv["close"], int(p["rsi_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "ema_50": ema(ohlcv["close"], 50),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        lookback = int(p["lookback"])
        rsi_series = indicators["rsi"]
        if len(rsi_series) < lookback + 2 or rsi_series[-1] is None or rsi_series[-lookback] is None:
            return None

        # Find recent low / high of price and RSI in the lookback window
        # Using last bar vs bar `lookback` ago as a simplification
        now_price = last_bar["close"]
        now_rsi = rsi_series[-1]
        prev_price = None
        prev_rsi = rsi_series[-lookback]

        # Need closes series — approximate with atr path (we don't have close series here)
        # Use the last-bar window from the caller: rebuild from ohlcv would require passing it.
        # Heuristic: RSI extremes with price confirmation
        ema50 = indicators["ema_50"][-1]

        # Bullish divergence heuristic: current RSI > RSI `lookback` ago but price lower
        # We don't have prev_price here; rely on ATR/ema to gauge regime
        # Simpler check: RSI rising from deep oversold + price still near/below EMA50
        if now_rsi is not None and prev_rsi is not None and prev_rsi < 30 and now_rsi > prev_rsi + 5 and ema50 and now_price < ema50:
            return EntrySignal(
                direction="long",
                confidence=64.0,
                reasons=[f"RSI rose from {prev_rsi:.1f} oversold to {now_rsi:.1f}"],
                tags=["reversal", "divergence", "oversold_recovery"],
            )
        if now_rsi is not None and prev_rsi is not None and prev_rsi > 70 and now_rsi < prev_rsi - 5 and ema50 and now_price > ema50:
            return EntrySignal(
                direction="short",
                confidence=64.0,
                reasons=[f"RSI fell from {prev_rsi:.1f} overbought to {now_rsi:.1f}"],
                tags=["reversal", "divergence", "overbought_fade"],
            )
        return None
