"""Funding-Skew Reversion proxy — fade extended momentum after blow-off.

Pattern origin:  Crypto-perp community: when funding rate goes extreme positive
                 (long crowded), price often mean-reverts. Without funding data
                 here, we proxy via 3-bar consecutive-up + RSI > 75 = exhaustion.
License:         MIT.
Notes:           True version belongs in news-monitor / signal-tracker once
                 funding rate is fed through; this is a price-only proxy.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, ema


class FundingSkewRevert(Strategy):
    metadata = StrategyMetadata(
        id="community.funding_skew_revert",
        name="Funding-Skew Reversion (proxy)",
        description="3-bar straight-up + RSI > 75 = fade. Reverse for short blow-offs.",
        source="community",
        source_url="https://research.binance.com/en/research-perpetual",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Counter-trend; small targets. Never use without HTF context.",
    )
    params = {
        "rsi_period": 14,
        "rsi_long_thresh": 25.0,
        "rsi_short_thresh": 75.0,
        "consec_bars": 3,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 1.5,
        "default_leverage": 2.0,
        "risk_pct": 0.8,
    }
    safe_bounds = {
        "rsi_period": [7, 21],
        "rsi_long_thresh": [15.0, 35.0],
        "rsi_short_thresh": [65.0, 85.0],
        "consec_bars": [2, 5],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 3.0],
        "risk_pct": [0.5, 1.2],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "rsi": rsi(ohlcv["close"], int(p["rsi_period"])),
            "ema_50": ema(ohlcv["close"], 50),
            "closes": ohlcv["close"],
        }

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["consec_bars"])
        r = indicators["rsi"]; C = indicators["closes"]
        if r[-1] is None or len(C) < n + 1:
            return None
        consec_up = all(C[-i] > C[-i - 1] for i in range(1, n + 1))
        consec_dn = all(C[-i] < C[-i - 1] for i in range(1, n + 1))
        if consec_up and r[-1] >= p["rsi_short_thresh"]:
            return EntrySignal(direction="short", confidence=62.0,
                               reasons=[f"{n} consecutive up bars + RSI {r[-1]:.1f}"],
                               tags=["mean_reversion", "blow_off"])
        if consec_dn and r[-1] <= p["rsi_long_thresh"]:
            return EntrySignal(direction="long", confidence=62.0,
                               reasons=[f"{n} consecutive down bars + RSI {r[-1]:.1f}"],
                               tags=["mean_reversion", "capitulation"])
        return None
