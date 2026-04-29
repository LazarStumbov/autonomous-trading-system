"""MFI Extreme — Money Flow Index volume-weighted RSI.

Pattern origin: Gene Quong & Avrum Soudack, Money Flow Index.
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class AqMfiExtreme(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.mfi_extreme",
        name="Money Flow Index Reversal",
        description="Long when MFI < 20 in uptrend; short when MFI > 80 in downtrend.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Volume-weighted; less prone to manipulation than RSI alone.",
    )
    params = {
        "mfi_period": 14,
        "trend_period": 100,
        "low": 20.0,
        "high": 80.0,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "mfi_period": [7, 21],
        "trend_period": [50, 200],
        "low": [10.0, 30.0],
        "high": [70.0, 90.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        c = ohlcv["close"]
        v = ohlcv["volume"]
        n = int(p["mfi_period"])
        tp = [(hi + lo + cl) / 3 for hi, lo, cl in zip(h, l, c)]
        money_flow = [t * vv for t, vv in zip(tp, v)]
        mfi = [None] * len(c)
        for i in range(n, len(c)):
            pos_mf = 0.0
            neg_mf = 0.0
            for j in range(i - n + 1, i + 1):
                if tp[j] > tp[j - 1]:
                    pos_mf += money_flow[j]
                elif tp[j] < tp[j - 1]:
                    neg_mf += money_flow[j]
            if neg_mf == 0:
                mfi[i] = 100.0
            else:
                ratio = pos_mf / neg_mf
                mfi[i] = 100 - (100 / (1 + ratio))
        return {
            "mfi": mfi,
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        m = indicators["mfi"][-1]
        et = indicators["ema_trend"][-1]
        if m is None or et is None:
            return None
        price = last_bar["close"]
        if m <= p["low"] and price > et:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"MFI {m:.1f} <= {p['low']}", "uptrend"],
                               tags=["mean_reversion", "mfi"])
        if m >= p["high"] and price < et:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"MFI {m:.1f} >= {p['high']}", "downtrend"],
                               tags=["mean_reversion", "mfi"])
        return None
