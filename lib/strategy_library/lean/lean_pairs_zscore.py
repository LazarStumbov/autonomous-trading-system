"""Z-score Reversion — single-asset z-score mean reversion (pairs simplification).

Pattern origin: Ed Thorp / Statistical arbitrage (Vidyamurthy "Pairs Trading").
Source URL:     https://github.com/QuantConnect/Lean
License:        Apache 2.0
Notes:          True pairs trading needs two assets; we use single-asset z-score on price vs SMA.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import sma, atr


class LeanPairsZscore(Strategy):
    metadata = StrategyMetadata(
        id="lean.pairs_zscore",
        name="Single-Asset Z-Score Reversion",
        description="z = (price - SMA) / stdev. Long when z < -2; short when z > 2.",
        source="lean",
        source_url="https://github.com/QuantConnect/Lean",
        license="Apache-2.0",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Reverts only when stationarity holds; trend kills it.",
    )
    params = {
        "lookback": 50,
        "z_threshold": 2.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [20, 100],
        "z_threshold": [1.5, 3.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.0, 2.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        n = int(p["lookback"])
        sma_n = sma(c, n)
        z = []
        for i in range(len(c)):
            if i < n - 1 or sma_n[i] is None:
                z.append(None)
            else:
                w = c[i - n + 1:i + 1]
                m = sma_n[i]
                var = sum((x - m) ** 2 for x in w) / n
                sd = var ** 0.5
                z.append((c[i] - m) / sd if sd > 0 else 0)
        return {
            "z": z,
            "sma": sma_n,
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        z = indicators["z"]
        if not z or z[-1] is None:
            return None
        zv = z[-1]
        if zv <= -p["z_threshold"]:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"z {zv:.2f} <= -{p['z_threshold']}"],
                               tags=["mean_reversion", "z_score"])
        if zv >= p["z_threshold"]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"z {zv:.2f} >= +{p['z_threshold']}"],
                               tags=["mean_reversion", "z_score"])
        return None
