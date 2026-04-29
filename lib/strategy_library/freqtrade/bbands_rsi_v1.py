"""BBands+RSI v1 — Bollinger band touch with RSI confirmation, long-only.

Pattern origin: classic freqtrade-strategies BBRSI variant.
Source URL:     https://github.com/freqtrade/freqtrade-strategies (BBRSI pattern reference)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          Long-only port; canonical strategy fades upper band too.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, bollinger_bands, atr


class BbandsRsiV1(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.bbands_rsi_v1",
        name="BBands RSI v1 (long-only)",
        description="Long when close pierces lower BB and RSI rebounds from <30.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Counter-trend; needs ranging regime.",
    )
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_max": 30.0,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "bb_period": [10, 40],
        "bb_std": [1.5, 3.0],
        "rsi_period": [7, 21],
        "rsi_max": [20.0, 40.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "bb": bollinger_bands(ohlcv["close"], int(p["bb_period"]), p["bb_std"]),
            "rsi": rsi(ohlcv["close"], int(p["rsi_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        bb_lower = indicators["bb"]["lower"]
        r = indicators["rsi"]
        if len(r) < 2 or r[-1] is None or r[-2] is None or bb_lower[-1] is None:
            return None
        price = last_bar["close"]
        # Bounce: price below lower BB on prev bar, RSI was <max but rising now
        if price <= bb_lower[-1] and r[-2] <= p["rsi_max"] and r[-1] > r[-2]:
            return EntrySignal(
                direction="long",
                confidence=68.0,
                reasons=[f"price <= lower BB", f"RSI rebound from {r[-2]:.1f}"],
                tags=["mean_reversion", "bb_touch"],
            )
        return None
