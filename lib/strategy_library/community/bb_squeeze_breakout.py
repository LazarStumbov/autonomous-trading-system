"""Bollinger Band squeeze → volatility expansion breakout.

Pattern: John Bollinger "squeeze" setup — narrow BBW precedes strong moves.
License: MIT (our implementation).
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import bollinger_bands, atr, ema, volume_ratio


class BbSqueezeBreakout(Strategy):
    metadata = StrategyMetadata(
        id="community.bb_squeeze_breakout",
        name="BB Squeeze Breakout",
        description="After BB width contracts below threshold, trade the expansion breakout with trend filter.",
        source="community",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Need real squeeze (consecutive low BBW bars) to avoid false expansions.",
    )

    params = {
        "squeeze_bbw_max": 0.025,
        "squeeze_lookback": 6,
        "volume_multiplier": 1.5,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 3.0,  # volatility breakouts have big R:R upside
        "default_leverage": 4.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "squeeze_bbw_max": [0.01, 0.05],
        "squeeze_lookback": [3, 12],
        "volume_multiplier": [1.0, 3.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {
            "bb": bollinger_bands(ohlcv["close"], 20, 2.0),
            "ema_50": ema(ohlcv["close"], 50),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        bbw = indicators["bb"]["width"]
        bb_upper = indicators["bb"]["upper"][-1]
        bb_lower = indicators["bb"]["lower"][-1]
        ema50 = indicators["ema_50"][-1]
        vr = indicators["vol_ratio"]
        price = last_bar["close"]

        # Need a real squeeze: last N bars (not including current) must all be below threshold
        lookback = int(p["squeeze_lookback"])
        if len(bbw) < lookback + 1 or ema50 is None:
            return None
        window = bbw[-lookback - 1:-1]
        if any(w is None or w > p["squeeze_bbw_max"] for w in window):
            return None
        if vr < p["volume_multiplier"]:
            return None

        # Breakout direction: which band did we break?
        if bb_upper is not None and price > bb_upper and price > ema50:
            return EntrySignal(
                direction="long",
                confidence=74.0,
                reasons=["BB squeeze", "break above upper BB", "price > EMA50", f"vol {vr:.2f}x"],
                tags=["breakout", "squeeze", "volatility_expansion"],
            )
        if bb_lower is not None and price < bb_lower and price < ema50:
            return EntrySignal(
                direction="short",
                confidence=74.0,
                reasons=["BB squeeze", "break below lower BB", "price < EMA50", f"vol {vr:.2f}x"],
                tags=["breakout", "squeeze", "volatility_expansion"],
            )
        return None
