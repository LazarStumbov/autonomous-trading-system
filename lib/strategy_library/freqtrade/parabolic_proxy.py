"""Parabolic Stop Proxy — accelerating EMA stack as Parabolic SAR substitute.

Pattern origin: J. Welles Wilder, Parabolic SAR concept ("New Concepts").
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          Approximates SAR via accelerating EMA gap.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class ParabolicProxy(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.parabolic_proxy",
        name="Parabolic SAR Proxy",
        description="Trade direction of EMA5 acceleration vs EMA20 (proxy for SAR flip).",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Approximation only; tighter than canonical SAR.",
    )
    params = {
        "fast": 5,
        "slow": 20,
        "min_gap_pct": 0.4,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast": [3, 10],
        "slow": [13, 50],
        "min_gap_pct": [0.1, 1.5],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "ema_f": ema(c, int(p["fast"])),
            "ema_s": ema(c, int(p["slow"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        f = indicators["ema_f"]
        s = indicators["ema_s"]
        if len(f) < 3 or f[-1] is None or s[-1] is None or f[-2] is None or s[-2] is None:
            return None
        gap = (f[-1] - s[-1]) / s[-1] * 100
        prev_gap = (f[-2] - s[-2]) / s[-2] * 100
        if gap >= p["min_gap_pct"] and gap > prev_gap:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"EMA gap accelerating: {prev_gap:.2f}->{gap:.2f}"],
                               tags=["momentum", "sar_proxy"])
        if gap <= -p["min_gap_pct"] and gap < prev_gap:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"EMA gap accelerating down: {prev_gap:.2f}->{gap:.2f}"],
                               tags=["momentum", "sar_proxy"])
        return None
