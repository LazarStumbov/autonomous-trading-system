"""MACD momentum — classic zero-line MACD crossover with volume confirmation.

Pattern origin: Gerald Appel (MACD, 1970s) — public domain.
License:        MIT (our implementation)

Long when MACD histogram crosses above zero and price above EMA 200 (uptrend filter).
Short mirrors.
"""

from __future__ import annotations

from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import macd, ema, atr, volume_ratio


class MacdMomentum(Strategy):
    metadata = StrategyMetadata(
        id="classic.macd_momentum_12_26_9",
        name="MACD Momentum 12/26/9",
        description="MACD histogram zero-cross with EMA200 trend filter and volume confirmation.",
        source="classic",
        source_url="https://www.investopedia.com/terms/m/macd.asp",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Classic MACD lags. Works best in trending markets; filter with higher-TF EMA.",
    )

    params = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "trend_ema": 200,
        "volume_multiplier": 1.2,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }

    safe_bounds = {
        "fast": [8, 16],
        "slow": [20, 35],
        "signal": [7, 14],
        "trend_ema": [100, 300],
        "volume_multiplier": [1.0, 2.5],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        closes = ohlcv["close"]
        return {
            "macd": macd(closes, int(p["fast"]), int(p["slow"]), int(p["signal"])),
            "ema_trend": ema(closes, int(p["trend_ema"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], closes, 14),
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        hist = indicators["macd"]["histogram"]
        ema_trend = indicators["ema_trend"][-1]
        vr = indicators["vol_ratio"]
        price = last_bar["close"]
        p = self._effective_params

        if hist[-1] is None or hist[-2] is None or ema_trend is None:
            return None

        # Long: histogram crossed above zero + price above trend EMA + volume confirmation
        if hist[-2] <= 0 < hist[-1] and price > ema_trend and vr >= p["volume_multiplier"]:
            return EntrySignal(
                direction="long",
                confidence=72.0,
                reasons=["MACD hist cross above zero", "price > EMA trend", f"vol {vr:.2f}x"],
                tags=["momentum", "macd", "trend_follow"],
            )
        if hist[-2] >= 0 > hist[-1] and price < ema_trend and vr >= p["volume_multiplier"]:
            return EntrySignal(
                direction="short",
                confidence=72.0,
                reasons=["MACD hist cross below zero", "price < EMA trend", f"vol {vr:.2f}x"],
                tags=["momentum", "macd", "trend_follow"],
            )
        return None
