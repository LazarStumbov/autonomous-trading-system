"""Aroon Cross — Tushar Chande's Aroon up/down indicator cross.

Pattern origin: Tushar Chande, Aroon indicator (1995).
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, cross_above, cross_below


class AqAroonCross(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.aroon_cross",
        name="Aroon Up/Down Cross",
        description="Long when Aroon-Up crosses above Aroon-Down with both > 50.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Trend onset signal; lag depends on period.",
    )
    params = {
        "aroon_period": 14,
        "min_strength": 50.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "aroon_period": [7, 30],
        "min_strength": [30.0, 70.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        n = int(p["aroon_period"])
        au, ad = [], []
        for i in range(len(h)):
            if i < n:
                au.append(None)
                ad.append(None)
            else:
                window_h = h[i - n:i + 1]
                window_l = l[i - n:i + 1]
                idx_h = window_h.index(max(window_h))
                idx_l = window_l.index(min(window_l))
                au.append((idx_h / n) * 100)
                ad.append((idx_l / n) * 100)
        return {
            "aroon_up": au,
            "aroon_down": ad,
            "atr_14": atr(h, l, ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        au = indicators["aroon_up"]
        ad = indicators["aroon_down"]
        if cross_above(au, ad) and au[-1] is not None and au[-1] >= p["min_strength"]:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"Aroon up cross, up={au[-1]:.0f}"],
                               tags=["trend_follow", "aroon"])
        if cross_below(au, ad) and ad[-1] is not None and ad[-1] >= p["min_strength"]:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"Aroon down cross, down={ad[-1]:.0f}"],
                               tags=["trend_follow", "aroon"])
        return None
