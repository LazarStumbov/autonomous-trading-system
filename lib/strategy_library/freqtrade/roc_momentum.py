"""ROC Momentum — rate-of-change crossover into positive territory.

Pattern origin: classic ROC indicator (Pring "Momentum Explained").
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class RocMomentum(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.roc_momentum",
        name="ROC Momentum Crossover",
        description="Long when ROC(N) crosses 0 with EMA50 trend filter.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="ROC is noise-prone short-term; long lookback helps.",
    )
    params = {
        "roc_period": 20,
        "trend_period": 50,
        "min_roc": 0.5,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "roc_period": [5, 50],
        "trend_period": [20, 100],
        "min_roc": [0.1, 3.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        n = int(p["roc_period"])
        roc = []
        for i in range(len(c)):
            if i < n or c[i - n] == 0:
                roc.append(None)
            else:
                roc.append((c[i] - c[i - n]) / c[i - n] * 100)
        return {
            "roc": roc,
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        r = indicators["roc"]
        et = indicators["ema_trend"][-1]
        if len(r) < 2 or r[-1] is None or r[-2] is None or et is None:
            return None
        price = last_bar["close"]
        if r[-2] <= 0 < r[-1] and r[-1] >= p["min_roc"] and price > et:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"ROC crossed 0 to {r[-1]:.2f}%"],
                               tags=["momentum"])
        if r[-2] >= 0 > r[-1] and r[-1] <= -p["min_roc"] and price < et:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"ROC crossed 0 to {r[-1]:.2f}%"],
                               tags=["momentum"])
        return None
