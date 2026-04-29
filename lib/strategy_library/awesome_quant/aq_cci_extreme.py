"""CCI Extreme — Donald Lambert's Commodity Channel Index extremes.

Pattern origin: Donald Lambert, "Commodities Channel Index: Tools for Trading Cyclical Trends" (1980).
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import sma, atr, ema


class AqCciExtreme(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.cci_extreme",
        name="CCI Extreme Reversal",
        description="Long if CCI < -200 in uptrend; short if CCI > +200 in downtrend.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Strong cycles; can stay extreme.",
    )
    params = {
        "cci_period": 20,
        "trend_period": 100,
        "extreme_low": -200.0,
        "extreme_high": 200.0,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "cci_period": [10, 40],
        "trend_period": [50, 200],
        "extreme_low": [-300.0, -100.0],
        "extreme_high": [100.0, 300.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        c = ohlcv["close"]
        tp = [(hi + lo + cl) / 3 for hi, lo, cl in zip(h, l, c)]
        n = int(p["cci_period"])
        sma_tp = sma(tp, n)
        cci = []
        for i in range(len(c)):
            if sma_tp[i] is None:
                cci.append(None)
            else:
                window = tp[i - n + 1:i + 1]
                m = sma_tp[i]
                mean_dev = sum(abs(x - m) for x in window) / n
                cci.append((tp[i] - m) / (0.015 * mean_dev) if mean_dev > 0 else 0)
        return {
            "cci": cci,
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        cv = indicators["cci"][-1]
        et = indicators["ema_trend"][-1]
        if cv is None or et is None:
            return None
        price = last_bar["close"]
        if cv <= p["extreme_low"] and price > et:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"CCI {cv:.1f} extreme low", "uptrend"],
                               tags=["mean_reversion", "cci"])
        if cv >= p["extreme_high"] and price < et:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"CCI {cv:.1f} extreme high", "downtrend"],
                               tags=["mean_reversion", "cci"])
        return None
