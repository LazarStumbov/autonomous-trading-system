"""Dual Momentum — Antonacci absolute + relative momentum (single-asset variant).

Pattern origin: Gary Antonacci, "Dual Momentum Investing" (2014).
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
Notes:          Single-asset port: relative-momentum component dropped, absolute only.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, sma


class LeanDualMomentum(Strategy):
    metadata = StrategyMetadata(
        id="lean.dual_momentum",
        name="Antonacci Dual Momentum (Absolute)",
        description="Long if 12-month return positive AND price > 12mo SMA.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Long-only; trend-following on monthly bar equivalent.",
    )
    params = {
        "lookback": 252,
        "stop_loss_atr_multiplier": 3.0,
        "take_profit_rr_ratio": 4.0,
        "default_leverage": 1.5,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [60, 365],
        "stop_loss_atr_multiplier": [2.0, 5.0],
        "take_profit_rr_ratio": [2.5, 6.0],
        "default_leverage": [1.0, 3.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "sma_long": sma(c, int(p["lookback"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "closes": c,
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        c = indicators["closes"]
        sl = indicators["sma_long"]
        if len(c) < n + 1 or sl[-1] is None:
            return None
        ret = (c[-1] - c[-n - 1]) / c[-n - 1] if c[-n - 1] > 0 else 0
        price = last_bar["close"]
        if ret > 0 and price > sl[-1]:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=[f"{n}-bar return +{ret*100:.1f}%", "above long-SMA"],
                               tags=["momentum", "macro"])
        return None
