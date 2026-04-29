"""BB+RSI scalper — BB band touch + RSI extreme. Short timeframe aggressive pattern.

Pattern source: widespread in freqtrade-strategies community (BBands/RSI combos).
Implementation: our own, MIT. No code copied.
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, bollinger_bands, atr, volume_ratio


class BbRsiScalper(Strategy):
    metadata = StrategyMetadata(
        id="community.bb_rsi_scalper",
        name="BB+RSI Scalper",
        description="Buy lower-BB touch with RSI <30; sell upper-BB touch with RSI >70. 5m-15m timeframe.",
        source="community",
        source_url="https://github.com/freqtrade/freqtrade-strategies (pattern reference)",
        license="MIT",
        version="1.0.0",
        timeframes=["5m", "15m"],
        asset_classes=["crypto_perp"],
        risk_notes="Short-TF scalper — high trade frequency. Fees matter. Needs tight SL.",
    )

    params = {
        "rsi_buy": 30.0,
        "rsi_sell": 70.0,
        "bb_period": 20,
        "bb_std": 2.0,
        "min_volume_ratio": 1.1,
        "stop_loss_atr_multiplier": 1.2,
        "take_profit_rr_ratio": 1.5,
        "default_leverage": 4.0,
        "risk_pct": 0.75,
    }

    safe_bounds = {
        "rsi_buy": [20.0, 35.0],
        "rsi_sell": [65.0, 80.0],
        "bb_std": [1.5, 3.0],
        "min_volume_ratio": [0.8, 2.5],
        "stop_loss_atr_multiplier": [0.8, 2.0],
        "take_profit_rr_ratio": [1.2, 2.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.3, 1.0],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "rsi": rsi(ohlcv["close"], 14),
            "bb": bollinger_bands(ohlcv["close"], int(p["bb_period"]), p["bb_std"]),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        price = last_bar["close"]
        r = indicators["rsi"][-1]
        bb_lower = indicators["bb"]["lower"][-1]
        bb_upper = indicators["bb"]["upper"][-1]
        vr = indicators["vol_ratio"]

        if None in (r, bb_lower, bb_upper):
            return None
        if vr < p["min_volume_ratio"]:
            return None

        if r <= p["rsi_buy"] and price <= bb_lower:
            return EntrySignal(
                direction="long",
                confidence=65.0 + min(15.0, (p["rsi_buy"] - r) * 2),
                reasons=[f"RSI {r:.1f} <= {p['rsi_buy']}", "price <= lower BB", f"vol {vr:.2f}x"],
                tags=["scalper", "bb_touch", "oversold"],
            )
        if r >= p["rsi_sell"] and price >= bb_upper:
            return EntrySignal(
                direction="short",
                confidence=65.0 + min(15.0, (r - p["rsi_sell"]) * 2),
                reasons=[f"RSI {r:.1f} >= {p['rsi_sell']}", "price >= upper BB", f"vol {vr:.2f}x"],
                tags=["scalper", "bb_touch", "overbought"],
            )
        return None
