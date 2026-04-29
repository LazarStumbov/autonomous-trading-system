"""VWAP reversion — fade excursions from session VWAP.

Pattern: well-documented intraday pattern (traders watch VWAP as magnet).
License: MIT (our implementation).
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal, ExitSignal
from lib.technical_indicators import vwap, atr, rsi


class VwapReversion(Strategy):
    metadata = StrategyMetadata(
        id="community.vwap_reversion",
        name="VWAP Reversion",
        description="Fade >2% VWAP excursions during active hours. Target: back to VWAP.",
        source="community",
        license="MIT",
        version="1.0.0",
        timeframes=["5m", "15m"],
        asset_classes=["crypto_perp"],
        risk_notes="Not for trending days — use regime filter. Session-reset sensitive.",
    )

    params = {
        "deviation_pct": 2.0,
        "rsi_confirm": True,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.5,  # target is VWAP, which is typically closer than 2R
        "default_leverage": 3.0,
        "risk_pct": 0.75,
    }

    safe_bounds = {
        "deviation_pct": [1.0, 4.0],
        "stop_loss_atr_multiplier": [1.0, 2.5],
        "take_profit_rr_ratio": [1.2, 2.5],
        "default_leverage": [1.0, 4.0],
        "risk_pct": [0.3, 1.0],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {
            "vwap": vwap(ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"]),
            "rsi": rsi(ohlcv["close"], 14),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        v = indicators["vwap"][-1]
        price = last_bar["close"]
        r = indicators["rsi"][-1]
        p = self._effective_params

        if v is None or v == 0:
            return None
        deviation = (price - v) / v * 100

        # Short: price above VWAP by >deviation_pct, RSI overbought
        if deviation >= p["deviation_pct"] and (not p["rsi_confirm"] or (r is not None and r > 65)):
            return EntrySignal(
                direction="short",
                confidence=66.0,
                reasons=[f"{deviation:+.2f}% above VWAP", f"RSI {r:.1f}" if r else "no RSI"],
                tags=["vwap", "reversion", "mean_revert"],
            )
        if deviation <= -p["deviation_pct"] and (not p["rsi_confirm"] or (r is not None and r < 35)):
            return EntrySignal(
                direction="long",
                confidence=66.0,
                reasons=[f"{deviation:+.2f}% below VWAP", f"RSI {r:.1f}" if r else "no RSI"],
                tags=["vwap", "reversion", "mean_revert"],
            )
        return None

    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        v = indicators["vwap"][-1]
        if v is None:
            return None
        price = last_bar["close"]
        direction = open_position.get("direction")
        # Close when we reach VWAP (the anchor)
        if direction == "long" and price >= v:
            return ExitSignal(reason="reached_vwap")
        if direction == "short" and price <= v:
            return ExitSignal(reason="reached_vwap")
        return None
