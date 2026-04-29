"""Inside-bar follow-through — Al Brooks-style price-action pattern.

Pattern origin:  Al Brooks ("Reading Price Charts Bar by Bar"). An inside bar
                 (high < prior high AND low > prior low) is a consolidation;
                 break of the inside-bar range in trend direction = entry.
License:         MIT.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema


class InsideBarFollowthrough(Strategy):
    metadata = StrategyMetadata(
        id="community.inside_bar_followthrough",
        name="Inside Bar Follow-Through (Brooks)",
        description="Inside bar break in trend direction (above EMA-50).",
        source="community",
        source_url="https://www.brookstradingcourse.com/",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Brooks emphasizes context; mechanical version misses many nuances.",
    )
    params = {
        "trend_ema": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "trend_ema": [20, 200],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {"ema": ema(ohlcv["close"], int(p["trend_ema"])),
                "highs": ohlcv["high"], "lows": ohlcv["low"],
                "closes": ohlcv["close"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        e = indicators["ema"]
        H = indicators["highs"]; L = indicators["lows"]; C = indicators["closes"]
        if len(H) < 3 or e[-1] is None:
            return None
        # bar -2 must be inside bar relative to bar -3
        ib_high = H[-2]; ib_low = L[-2]
        ref_high = H[-3]; ref_low = L[-3]
        is_inside = ib_high < ref_high and ib_low > ref_low
        if not is_inside:
            return None
        c = last_bar["close"]
        # break of inside-bar high in uptrend = long
        if c > ib_high and c > e[-1]:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["inside-bar break long, above EMA"],
                               tags=["price_action", "inside_bar", "brooks"])
        if c < ib_low and c < e[-1]:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["inside-bar break short, below EMA"],
                               tags=["price_action", "inside_bar", "brooks"])
        return None
