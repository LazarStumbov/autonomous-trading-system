"""EMA crossover — textbook trend-following.

Pattern origin: public domain (documented in every TA textbook).
License:        MIT (our implementation)

Enters long on 9-EMA crossing above 21-EMA with price above 50-EMA for trend filter.
Short mirrors. One of the most-tested patterns in crypto day trading.
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, cross_above, cross_below


class EmaCross(Strategy):
    metadata = StrategyMetadata(
        id="classic.ema_cross_9_21_50",
        name="EMA Cross 9/21/50",
        description="9-EMA crosses 21-EMA with price/50-EMA trend filter.",
        source="classic",
        source_url="https://www.investopedia.com/terms/e/ema.asp",
        license="MIT",
        version="1.0.0",
        timeframes=["5m", "15m", "1h"],
        asset_classes=["crypto_perp", "crypto_spot"],
        risk_notes="Whipsaws in ranges. Performs best in trending regimes.",
    )

    params = {
        "fast": 9,
        "medium": 21,
        "slow": 50,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "fast": [5, 12],
        "medium": [15, 30],
        "slow": [40, 100],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        closes = ohlcv["close"]
        highs = ohlcv["high"]
        lows = ohlcv["low"]
        p = self._effective_params
        return {
            "ema_fast": ema(closes, int(p["fast"])),
            "ema_medium": ema(closes, int(p["medium"])),
            "ema_slow": ema(closes, int(p["slow"])),
            "atr_14": atr(highs, lows, closes, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        ef = indicators["ema_fast"]
        em = indicators["ema_medium"]
        es = indicators["ema_slow"]
        price = last_bar["close"]

        if es[-1] is None or em[-1] is None or ef[-1] is None:
            return None

        # Long: fast crosses above medium, price above slow
        if cross_above(ef, em) and price > es[-1]:
            return EntrySignal(
                direction="long",
                confidence=72.0,
                reasons=["EMA fast cross above medium", "price > slow EMA"],
                tags=["trend_follow", "crossover"],
            )
        if cross_below(ef, em) and price < es[-1]:
            return EntrySignal(
                direction="short",
                confidence=72.0,
                reasons=["EMA fast cross below medium", "price < slow EMA"],
                tags=["trend_follow", "crossover"],
            )
        return None
