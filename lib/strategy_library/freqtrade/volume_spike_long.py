"""Volume Spike Long — extreme volume + bullish close = continuation.

Pattern origin: Stockbee "Episodic Pivots" / volume-up-day concept.
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import volume_ratio, ema, atr, pct_change


class VolumeSpikeLong(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.volume_spike_long",
        name="Volume Spike Continuation",
        description="Extreme volume + bullish bar > 2% gain = momentum continuation long.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Spike can mark exhaustion top; require trend filter.",
    )
    params = {
        "vol_multiplier": 3.0,
        "min_pct_gain": 2.0,
        "trend_period": 50,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "vol_multiplier": [1.5, 5.0],
        "min_pct_gain": [0.5, 5.0],
        "trend_period": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "bar_pct": pct_change(c, 1),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        vr = indicators["vol_ratio"]
        et = indicators["ema_trend"][-1]
        bp = indicators["bar_pct"]
        if et is None or bp is None:
            return None
        price = last_bar["close"]
        if vr >= p["vol_multiplier"] and bp >= p["min_pct_gain"] and price > et:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=[f"vol {vr:.2f}x", f"+{bp:.2f}%", "above trend"],
                               tags=["volume", "continuation"])
        return None
