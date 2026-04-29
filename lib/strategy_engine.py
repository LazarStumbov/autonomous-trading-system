"""Strategy engine: pluggable interface for all trading strategies.

Every strategy — whether internal, imported from freqtrade/jesse, or auto-generated
by the self-improvement loop — implements the Strategy base class. The screener
calls these uniformly; the backtester replays them against historical data with
the same code path; the self-improver tunes them via their declared safe_bounds.

Design goals:
  - No hard dependency on pandas/numpy (pure Python OHLCV dicts work)
  - Strategies declare what they need via metadata, not by importing infrastructure
  - The risk engine remains the final gate; sizing here is a *suggestion*
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional, Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.technical_indicators import ema, sma, rsi, macd, bollinger_bands, atr, donchian, supertrend, vwap  # noqa: E402, F401


# ── Canonical mode values ────────────────────────────────────────────────────
MODE_DISABLED = "disabled"
MODE_BACKTEST = "backtest"
MODE_PAPER = "paper"
MODE_LIVE = "live"
VALID_MODES = {MODE_DISABLED, MODE_BACKTEST, MODE_PAPER, MODE_LIVE}


# ── Data containers ──────────────────────────────────────────────────────────
@dataclass
class StrategyMetadata:
    """Static metadata describing a strategy. Required for registry registration."""

    id: str                                    # unique slug, e.g. "internal.momentum_breakout"
    name: str
    description: str = ""
    source: str = "internal"                   # "internal", "freqtrade", "jesse", ...
    source_url: str = ""
    source_commit: str = ""
    license: str = "MIT"
    version: str = "1.0.0"
    timeframes: list[str] = field(default_factory=lambda: ["1h"])
    asset_classes: list[str] = field(default_factory=lambda: ["crypto_perp"])
    preferred_assets: list[str] = field(default_factory=list)
    risk_notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EntrySignal:
    """A strategy's decision to open a position."""

    direction: str                             # "long" or "short"
    confidence: float = 50.0                   # 0-100, strategy-internal
    reasons: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # e.g. ["breakout", "volume_spike"]


@dataclass
class ExitSignal:
    """A strategy's decision to close an open position."""

    reason: str                                # e.g. "rsi_divergence", "time_stop"
    partial: bool = False                      # True = close only partial_pct
    partial_pct: float = 100.0


@dataclass
class Sizing:
    """Sizing suggestion. Risk engine still has veto power."""

    stop_loss: float
    take_profit: float
    suggested_leverage: float = 3.0
    suggested_risk_pct: float = 1.0            # % of capital to risk on this trade
    position_fraction: float = 1.0             # fraction of "normal" size (for confidence scaling)
    rr_ratio: float = 2.0


# ── Base class ───────────────────────────────────────────────────────────────
class Strategy:
    """Subclass this to define a strategy.

    Minimum override:
      - metadata (class attribute)
      - params (class attribute with default parameter values)
      - safe_bounds (class attribute with [min, max] per tunable param)
      - populate_indicators(ohlcv) -> dict
      - entry_signal(indicators, last_bar) -> Optional[EntrySignal]

    Optional overrides:
      - exit_signal(...) -> Optional[ExitSignal]
      - sizing(...) -> Sizing
    """

    # Subclasses MUST override
    metadata: StrategyMetadata = None
    params: dict = {}
    safe_bounds: dict = {}

    def __init__(self, params: Optional[dict] = None):
        """Instantiate with optional parameter overrides (must stay inside safe_bounds)."""
        self._effective_params = dict(self.params)
        if params:
            for k, v in params.items():
                if k in self.safe_bounds:
                    lo, hi = self.safe_bounds[k]
                    if not (lo <= v <= hi):
                        raise ValueError(
                            f"Param '{k}'={v} out of safe bounds [{lo}, {hi}] for {self.strategy_id}"
                        )
                self._effective_params[k] = v

    # ── Identity ─────────────────────────────────────────────────────────────
    @property
    def strategy_id(self) -> str:
        if self.metadata is None:
            raise NotImplementedError(f"{type(self).__name__}.metadata is not set")
        return self.metadata.id

    @property
    def effective_params(self) -> dict:
        return dict(self._effective_params)

    # ── Required overrides ───────────────────────────────────────────────────
    def populate_indicators(self, ohlcv: dict) -> dict:
        """Compute all indicators the strategy needs.

        Args:
            ohlcv: dict with keys 'open', 'high', 'low', 'close', 'volume' -> list[float]

        Returns:
            dict of indicator_name -> list[float] (aligned with candle indices)
        """
        raise NotImplementedError

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        """Decide whether to enter a position on the current (last) candle."""
        raise NotImplementedError

    # ── Optional overrides ───────────────────────────────────────────────────
    def exit_signal(self, indicators: dict, last_bar: dict, open_position: dict) -> Optional[ExitSignal]:
        """Decide whether to close an open position early. Default: no early exit."""
        return None

    def sizing(self, entry_price: float, atr_value: float, entry: EntrySignal) -> Sizing:
        """Default sizing: 2x ATR stop, 2:1 R:R. Override for strategy-specific sizing."""
        p = self._effective_params
        sl_mult = p.get("stop_loss_atr_multiplier", 2.0)
        rr = p.get("take_profit_rr_ratio", 2.0)
        lev = p.get("default_leverage", 3.0)
        sl_distance = atr_value * sl_mult

        if entry.direction == "long":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + sl_distance * rr
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - sl_distance * rr

        return Sizing(
            stop_loss=round(stop_loss, 6),
            take_profit=round(take_profit, 6),
            suggested_leverage=lev,
            suggested_risk_pct=p.get("risk_pct", 1.0),
            position_fraction=min(1.0, entry.confidence / 100.0),
            rr_ratio=rr,
        )


# ── OHLCV helpers ────────────────────────────────────────────────────────────
def ohlcv_from_candles(candles: list[dict]) -> dict:
    """Convert the project's standard candle list into column arrays."""
    return {
        "open": [c["open"] for c in candles],
        "high": [c["high"] for c in candles],
        "low": [c["low"] for c in candles],
        "close": [c["close"] for c in candles],
        "volume": [c["volume"] for c in candles],
        "timestamp": [c.get("timestamp") for c in candles],
    }


def last_bar(ohlcv: dict) -> dict:
    """Return a dict representing the most recent candle."""
    return {
        "open": ohlcv["open"][-1],
        "high": ohlcv["high"][-1],
        "low": ohlcv["low"][-1],
        "close": ohlcv["close"][-1],
        "volume": ohlcv["volume"][-1],
        "timestamp": ohlcv["timestamp"][-1] if ohlcv.get("timestamp") else None,
        "index": len(ohlcv["close"]) - 1,
    }


# ── Setup formatter (bridges strategy output to screener.setups.json shape) ──
def build_setup_from_signal(
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    entry: EntrySignal,
    sizing: Sizing,
    entry_price: float,
    atr_value: float,
    reasons: Optional[list[str]] = None,
) -> dict:
    """Produce a setup dict in the shape screener / confluence_detector expect."""
    sl_distance = abs(entry_price - sizing.stop_loss)
    return {
        "symbol": symbol,
        "strategy": strategy.strategy_id,
        "strategy_source": strategy.metadata.source,
        "strategy_mode": None,                 # filled in by loader
        "direction": entry.direction,
        "timeframe": timeframe,
        "entry_price": round(entry_price, 6),
        "stop_loss": sizing.stop_loss,
        "take_profit": sizing.take_profit,
        "sl_distance_pct": round(sl_distance / entry_price * 100, 2) if entry_price else 0,
        "rr_ratio": sizing.rr_ratio,
        "confidence": round(entry.confidence, 1),
        "leverage": sizing.suggested_leverage,
        "suggested_risk_pct": sizing.suggested_risk_pct,
        "position_fraction": sizing.position_fraction,
        "reasons": reasons or entry.reasons,
        "tags": entry.tags,
        "atr": round(atr_value, 6) if atr_value else None,
    }


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Strategy engine loaded:")
    print(f"  VALID_MODES = {VALID_MODES}")
    print(f"  Indicator helpers: ema, sma, rsi, macd, bollinger_bands, atr, donchian, supertrend, vwap")
    print("  Base class: Strategy (abstract)")
    print("  Run strategy_loader.py --self-test for full validation.")
