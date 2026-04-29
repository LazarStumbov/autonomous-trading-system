"""TradingView — Liquidity Sweep / SMC-Lite (PineCoders open-source).

Pattern origin:  Smart Money Concepts (ICT-inspired) liquidity-sweep entry.
                 Vetted open-source LuxAlgo / PineCoders implementations exist;
                 this is a textbook minimal port.
Source URL:      https://www.tradingview.com/script/CdW3Y8U7-Smart-Money-Concepts-LuxAlgo/
License:         MIT (our impl). Mechanically: sweep prior swing high/low and
                 close back inside the range = liquidity grab.
Notes:           Lookback for "swing" is small (5 bars) since we don't have
                 multi-bar pivot detection. Treat as scalper-style setup.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr


class TVSmartMoneyLiquiditySweep(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.smc_liquidity_sweep",
        name="TradingView SMC Liquidity Sweep",
        description="Sweep prior swing high/low and close back inside = reversal entry.",
        source="tradingview",
        source_url="https://www.tradingview.com/script/CdW3Y8U7/",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="ICT-derived; many imitators on TV — keep impl mechanical.",
    )
    params = {
        "swing_lookback": 5,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "swing_lookback": [3, 15],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {"atr": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
                "highs": ohlcv["high"], "lows": ohlcv["low"], "closes": ohlcv["close"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["swing_lookback"])
        H = indicators["highs"]; L = indicators["lows"]; C = indicators["closes"]
        if len(H) < n + 2:
            return None
        # prior swing range from bars [-n-1 : -1] (excluding current)
        prior_high = max(H[-n - 1:-1])
        prior_low = min(L[-n - 1:-1])
        cur_h = H[-1]; cur_l = L[-1]; cur_c = C[-1]
        # bullish sweep: wick below prior_low but close back inside
        if cur_l < prior_low and cur_c > prior_low:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"swept {n}-bar low; close reclaimed range"],
                               tags=["liquidity_sweep", "reversal", "smc"])
        # bearish sweep: wick above prior_high but close back inside
        if cur_h > prior_high and cur_c < prior_high:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=[f"swept {n}-bar high; close rejected range"],
                               tags=["liquidity_sweep", "reversal", "smc"])
        return None
