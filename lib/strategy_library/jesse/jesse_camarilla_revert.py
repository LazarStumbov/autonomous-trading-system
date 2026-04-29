"""Camarilla Reversion — revert from H3/L3 levels.

Pattern origin: Nick Stott's Camarilla Equation (Slim Stops Floor Trader Pivots).
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr


class JesseCamarillaRevert(Strategy):
    metadata = StrategyMetadata(
        id="jesse.camarilla_revert",
        name="Camarilla H3/L3 Reversion",
        description="Fade rejection at Camarilla H3/L3 levels (range day setup).",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Range-bound markets only; fails on trend days.",
    )
    params = {
        "lookback": 24,
        "stop_loss_atr_multiplier": 1.2,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [12, 48],
        "stop_loss_atr_multiplier": [0.8, 2.5],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
            "closes": ohlcv["close"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        h = indicators["highs"]
        l = indicators["lows"]
        c = indicators["closes"]
        if len(h) < n + 1:
            return None
        prev_h = max(h[-n - 1:-1])
        prev_l = min(l[-n - 1:-1])
        prev_c = c[-2]
        rng = prev_h - prev_l
        h3 = prev_c + 1.1 * rng / 4
        l3 = prev_c - 1.1 * rng / 4
        price = last_bar["close"]
        if last_bar["high"] >= h3 and price < h3:
            return EntrySignal(direction="short", confidence=65.0,
                               reasons=["rejected at Camarilla H3"],
                               tags=["mean_reversion", "camarilla"])
        if last_bar["low"] <= l3 and price > l3:
            return EntrySignal(direction="long", confidence=65.0,
                               reasons=["bounce off Camarilla L3"],
                               tags=["mean_reversion", "camarilla"])
        return None
