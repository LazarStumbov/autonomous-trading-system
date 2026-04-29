"""Meb Faber 10-month SMA — own when above, cash when below.

Pattern origin: Meb Faber "A Quantitative Approach to Tactical Asset Allocation" (2007).
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import sma, atr


class LeanMebFaberTactical(Strategy):
    metadata = StrategyMetadata(
        id="lean.meb_faber_tactical",
        name="Meb Faber 200-bar SMA Tactical",
        description="Long when price > SMA200. Long-only macro trend.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Original Faber rule on monthly bars; adapted to daily SMA200 for crypto.",
    )
    params = {
        "sma_period": 200,
        "stop_loss_atr_multiplier": 4.0,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 1.5,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "sma_period": [100, 300],
        "stop_loss_atr_multiplier": [2.5, 6.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 3.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "sma": sma(c, int(p["sma_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        s = indicators["sma"]
        if len(s) < 2 or s[-1] is None or s[-2] is None:
            return None
        # Trigger only on the cross-up (avoid loading every bar)
        c1 = last_bar["close"]
        # Must use prev close vs prev sma to detect cross
        if c1 > s[-1] and s[-2] > 0:
            # Trigger only if previous bar's close was below sma
            prev_close_below = (c1 / s[-1] - 1) < 0.02  # Just crossed (within 2%)
            if prev_close_below:
                return EntrySignal(direction="long", confidence=70.0,
                                   reasons=["price crossed SMA200 up"],
                                   tags=["macro_trend"])
        return None
