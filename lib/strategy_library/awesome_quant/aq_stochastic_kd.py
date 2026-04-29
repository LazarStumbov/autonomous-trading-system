"""Stochastic K/D Cross — George Lane's stochastic oscillator.

Pattern origin: George C. Lane, Stochastic Oscillator (late 1950s).
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import sma, atr, ema, cross_above, cross_below


class AqStochasticKd(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.stochastic_kd",
        name="Stochastic %K/%D Cross",
        description="%K crosses above %D below 30 = long; mirror for short.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Useful in range; whipsaws in trend.",
    )
    params = {
        "k_period": 14,
        "k_smooth": 3,
        "d_period": 3,
        "buy_threshold": 30.0,
        "sell_threshold": 70.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "k_period": [5, 21],
        "k_smooth": [1, 5],
        "d_period": [1, 5],
        "buy_threshold": [15.0, 40.0],
        "sell_threshold": [60.0, 85.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        c = ohlcv["close"]
        n = int(p["k_period"])
        raw_k = []
        for i in range(len(c)):
            if i < n - 1:
                raw_k.append(None)
            else:
                hh = max(h[i - n + 1:i + 1])
                ll = min(l[i - n + 1:i + 1])
                raw_k.append((c[i] - ll) / (hh - ll) * 100 if hh > ll else 50.0)
        # Smooth K
        k_clean = [v for v in raw_k if v is not None]
        smoothed = sma(k_clean, int(p["k_smooth"]))
        pad = len(raw_k) - len(smoothed)
        k = [None] * pad + smoothed
        # %D = SMA(K, d_period)
        d_clean = [v for v in k if v is not None]
        d_sma = sma(d_clean, int(p["d_period"]))
        pad2 = len(k) - len(d_sma)
        d = [None] * pad2 + d_sma
        return {
            "k": k,
            "d": d,
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        k = indicators["k"]
        d = indicators["d"]
        if cross_above(k, d) and k[-1] is not None and k[-1] < p["buy_threshold"]:
            return EntrySignal(direction="long", confidence=64.0,
                               reasons=[f"%K cross above %D at {k[-1]:.1f}"],
                               tags=["oscillator", "stochastic"])
        if cross_below(k, d) and k[-1] is not None and k[-1] > p["sell_threshold"]:
            return EntrySignal(direction="short", confidence=62.0,
                               reasons=[f"%K cross below %D at {k[-1]:.1f}"],
                               tags=["oscillator", "stochastic"])
        return None
