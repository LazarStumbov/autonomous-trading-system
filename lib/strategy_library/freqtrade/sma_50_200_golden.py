"""SMA Golden/Death Cross — classic SMA50 vs SMA200 institutional trend signal.

Pattern origin: standard market-technician definition (Murphy, "Technical Analysis of Financial Markets").
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import sma, atr, cross_above, cross_below


class Sma50200Golden(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.sma_50_200_golden",
        name="SMA 50/200 Golden Cross",
        description="Long on SMA50 > SMA200 cross; short on death cross.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Slow signal; suited for higher timeframes.",
    )
    params = {
        "fast": 50,
        "slow": 200,
        "stop_loss_atr_multiplier": 3.0,
        "take_profit_rr_ratio": 4.0,
        "default_leverage": 2.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast": [20, 80],
        "slow": [100, 300],
        "stop_loss_atr_multiplier": [2.0, 4.5],
        "take_profit_rr_ratio": [2.5, 6.0],
        "default_leverage": [1.0, 4.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "sma_fast": sma(c, int(p["fast"])),
            "sma_slow": sma(c, int(p["slow"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        f = indicators["sma_fast"]
        s = indicators["sma_slow"]
        if cross_above(f, s):
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["SMA golden cross"],
                               tags=["trend_follow", "macro"])
        if cross_below(f, s):
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["SMA death cross"],
                               tags=["trend_follow", "macro"])
        return None
