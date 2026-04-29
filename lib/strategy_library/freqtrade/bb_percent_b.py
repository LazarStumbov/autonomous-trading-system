"""BB %B Reversion — fade extreme %B values.

Pattern origin: John Bollinger, %B normalized indicator (Bollinger Bands).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import bollinger_bands, atr, sma


class BbPercentB(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.bb_percent_b",
        name="BB %B Mean Reversion",
        description="Long on %B<0.05 (price below lower band); short on %B>0.95.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Pure mean-reversion. Avoid in strong trends.",
    )
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "low_pct_b": 0.05,
        "high_pct_b": 0.95,
        "trend_filter_period": 200,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "bb_period": [10, 30],
        "bb_std": [1.5, 3.0],
        "low_pct_b": [0.0, 0.2],
        "high_pct_b": [0.8, 1.0],
        "trend_filter_period": [100, 300],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.0, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        bb = bollinger_bands(c, int(p["bb_period"]), p["bb_std"])
        pct_b = []
        for i in range(len(c)):
            u = bb["upper"][i]
            l = bb["lower"][i]
            if u is None or l is None or u == l:
                pct_b.append(None)
            else:
                pct_b.append((c[i] - l) / (u - l))
        return {
            "pct_b": pct_b,
            "trend": sma(c, int(p["trend_filter_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        pb = indicators["pct_b"][-1]
        t = indicators["trend"][-1]
        if pb is None or t is None:
            return None
        price = last_bar["close"]
        if pb <= p["low_pct_b"] and price > t:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"%B {pb:.3f} <= {p['low_pct_b']}", "above SMA200"],
                               tags=["mean_reversion"])
        if pb >= p["high_pct_b"] and price < t:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"%B {pb:.3f} >= {p['high_pct_b']}", "below SMA200"],
                               tags=["mean_reversion"])
        return None
