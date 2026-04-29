"""Dual Thrust — Michael Chalek's classic intraday breakout system.

Pattern origin:  Michael Chalek, 1990s; widely used in CTA programs and
                 systematic crypto bots. Defines today's range as a function
                 of N-period (high-low extremes), then breaks of K1*range up /
                 K2*range down trigger entries.
License:         MIT (our impl). Concept public.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal


class DualThrustClassic(Strategy):
    metadata = StrategyMetadata(
        id="classic.dual_thrust",
        name="Dual Thrust (Chalek)",
        description="Range breakout sized by N-bar HH/LL spread.",
        source="classic",
        source_url="https://www.investopedia.com/terms/d/dualthrust.asp",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="K1/K2 asymmetric — tune by regime.",
    )
    params = {
        "n_period": 4,
        "k1_long": 0.7,
        "k2_short": 0.7,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "n_period": [3, 14],
        "k1_long": [0.3, 1.5],
        "k2_short": [0.3, 1.5],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        n = int(p["n_period"])
        H = ohlcv["high"]; L = ohlcv["low"]; C = ohlcv["close"]
        # range = max(HH(n)-LC(n), HC(n)-LL(n)) on the prior N bars
        ranges = [None] * len(C)
        for i in range(n, len(C)):
            window_h = max(H[i - n:i])
            window_l = min(L[i - n:i])
            window_c = C[i - n:i]
            ranges[i] = max(window_h - min(window_c), max(window_c) - window_l)
        return {"opens": ohlcv["open"], "ranges": ranges}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        opens = indicators["opens"]; ranges = indicators["ranges"]
        if ranges[-1] is None:
            return None
        o = opens[-1]; r = ranges[-1]
        c = last_bar["close"]
        long_trigger = o + p["k1_long"] * r
        short_trigger = o - p["k2_short"] * r
        if c > long_trigger:
            return EntrySignal(direction="long", confidence=65.0,
                               reasons=[f"close > open + {p['k1_long']}*range"],
                               tags=["dual_thrust", "breakout"])
        if c < short_trigger:
            return EntrySignal(direction="short", confidence=65.0,
                               reasons=[f"close < open - {p['k2_short']}*range"],
                               tags=["dual_thrust", "breakout"])
        return None
