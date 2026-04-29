"""EMA Cross Trend — fast/slow EMA cross filtered by EMA200 trend.

Pattern origin: textbook trend-following (Pring, "Technical Analysis Explained").
Source URL:     https://github.com/freqtrade/freqtrade-strategies (EMA cross variants)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, cross_above, cross_below


class EmaCrossTrend(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.ema_cross_trend",
        name="EMA Cross with Trend Filter",
        description="EMA10/EMA30 cross only when on the same side of EMA200.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Trend filter reduces whipsaw but lags reversals.",
    )
    params = {
        "fast": 10,
        "slow": 30,
        "trend": 200,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast": [5, 20],
        "slow": [20, 60],
        "trend": [100, 300],
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "ema_fast": ema(c, int(p["fast"])),
            "ema_slow": ema(c, int(p["slow"])),
            "ema_trend": ema(c, int(p["trend"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        ef = indicators["ema_fast"]
        es = indicators["ema_slow"]
        et = indicators["ema_trend"]
        if len(ef) < 2 or et[-1] is None or es[-1] is None:
            return None
        price = last_bar["close"]
        if cross_above(ef, es) and price > et[-1]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["fast crossed above slow", "above EMA200"],
                               tags=["trend_follow", "cross"])
        if cross_below(ef, es) and price < et[-1]:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["fast crossed below slow", "below EMA200"],
                               tags=["trend_follow", "cross"])
        return None
