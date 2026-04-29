"""TradingView — VWAP-as-POC reversion (volume-profile lite).

Pattern origin:  Volume profile / point-of-control reversion. Without intra-bar
                 volume distribution we approximate POC via VWAP, treating
                 deviations beyond N*std as fade opportunities back to VWAP.
Source URL:      https://www.tradingview.com/scripts/volumeprofile/
License:         MIT.
Notes:           Stocks/futures get richer profile data; for crypto perps VWAP
                 is the most accessible proxy.
"""

from __future__ import annotations
import math
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import vwap


class TVVolumeProfilePOC(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.volume_profile_poc",
        name="TradingView VWAP-POC Reversion",
        description="Fade extreme deviations from VWAP back to mean.",
        source="tradingview",
        source_url="https://www.tradingview.com/scripts/volumeprofile/",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Mean-reversion in trends bleeds; gate with regime filter.",
    )
    params = {
        "stddev_threshold": 2.0,
        "lookback": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "stddev_threshold": [1.5, 3.5],
        "lookback": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        v = vwap(ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"])
        return {"vwap": v, "closes": ohlcv["close"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        v = indicators["vwap"]; C = indicators["closes"]
        if len(C) < n + 1 or v[-1] is None:
            return None
        # rolling stdev of (close - vwap)
        diffs = [C[i] - v[i] for i in range(len(C) - n, len(C)) if v[i] is not None]
        if len(diffs) < n // 2:
            return None
        mean_d = sum(diffs) / len(diffs)
        var = sum((d - mean_d) ** 2 for d in diffs) / len(diffs)
        std = math.sqrt(var) if var > 0 else 0.0
        if std == 0:
            return None
        z = (C[-1] - v[-1]) / std
        if z <= -p["stddev_threshold"]:
            return EntrySignal(direction="long", confidence=64.0,
                               reasons=[f"close {z:.1f}σ below VWAP"],
                               tags=["mean_reversion", "vwap"])
        if z >= p["stddev_threshold"]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"close {z:.1f}σ above VWAP"],
                               tags=["mean_reversion", "vwap"])
        return None
