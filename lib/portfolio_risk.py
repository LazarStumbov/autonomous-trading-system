"""Portfolio-level risk analytics (Workstream 4 — Stage 1).

The existing lib.risk_engine handles per-trade gating well (size, leverage,
drawdown, correlation count, R:R). What's missing is the institutional view
of the portfolio AS A PORTFOLIO: VaR, CVaR, pairwise correlations, and
factor exposures across open positions.

Stage 1 ships VaR/CVaR (parametric + historical) and a pairwise correlation
matrix. Factor exposure beyond BTC-beta and stress testing live in Workstream 4
Phase B / Stage 7.

Design choices:
- All math is parametric or historical-empirical. No external dependencies
  beyond numpy/pandas (already in requirements).
- Returns are computed from 1h OHLCV pulled via paper_engine / OKX public
  endpoints — same data path the rest of the system uses.
- Per-asset return histories are cached in-process for the lifetime of the
  caller. Each snapshot is independent of others; no global state.
- VaR is reported in *USD* on the gross notional, not as a percentage, so
  the dollar figure can be compared directly against MAX_DAILY_DRAWDOWN.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Z-score for one-sided 95% confidence parametric VaR
_Z_95 = 1.6449


@dataclass
class Position:
    """Minimal open-position fields needed for portfolio analytics."""
    asset: str
    direction: str        # 'long' / 'short' / 'yes' / 'no'
    notional_usd: float   # gross notional (entry_price * quantity * leverage)
    pillar: str = "market"


@dataclass
class RiskSnapshot:
    snapshot_at: str
    capital_usd: float
    open_position_count: int
    gross_exposure_usd: float
    net_exposure_usd: float
    var_95_1d_usd: float
    cvar_95_1d_usd: float
    var_95_pct: float
    avg_pairwise_correlation: Optional[float]
    max_pairwise_correlation: Optional[float]
    factor_exposures: dict
    notes: str = ""

    def to_db_row(self) -> dict:
        import json
        return {
            "snapshot_at": self.snapshot_at,
            "capital_usd": self.capital_usd,
            "open_position_count": self.open_position_count,
            "gross_exposure_usd": self.gross_exposure_usd,
            "net_exposure_usd": self.net_exposure_usd,
            "var_95_1d_usd": self.var_95_1d_usd,
            "cvar_95_1d_usd": self.cvar_95_1d_usd,
            "var_95_pct": self.var_95_pct,
            "avg_pairwise_correlation": self.avg_pairwise_correlation,
            "max_pairwise_correlation": self.max_pairwise_correlation,
            "factor_exposures_json": json.dumps(self.factor_exposures),
            "notes": self.notes,
        }


def fetch_returns(symbol: str, timeframe: str = "1h", limit: int = 168) -> np.ndarray:
    """Pull recent close-to-close log returns for symbol.

    168 1h bars = 7 days. Returns empty array on fetch failure rather than
    raising — the snapshot caller is built to tolerate partial coverage.
    """
    try:
        from lib.paper_engine import get_public_ohlcv, _YAHOO_TICKER_MAP
        from .brokers.okx_adapter import get_exchange  # type: ignore
    except Exception:
        return np.array([])

    candles = None
    try:
        if symbol.upper() in _YAHOO_TICKER_MAP:
            candles = get_public_ohlcv(symbol, timeframe, limit)
        else:
            import ccxt  # type: ignore
            ex = ccxt.okx({"options": {"defaultType": "swap"}, "enableRateLimit": True})
            candles = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    except Exception as e:
        print(f"[portfolio_risk] fetch_returns({symbol}) failed: {e}")
        return np.array([])

    if not candles or len(candles) < 2:
        return np.array([])
    closes = np.array([c[4] for c in candles], dtype=float)
    closes = closes[closes > 0]
    if len(closes) < 2:
        return np.array([])
    return np.diff(np.log(closes))


def correlation_matrix(positions: list[Position], timeframe: str = "1h") -> dict:
    """Pairwise correlation across the open positions' assets.

    Polymarket positions are excluded (no continuous return series). Returns a
    dict keyed by (asset_a, asset_b) tuples for serialization to
    correlation_matrix_daily, plus avg + max across the upper triangle.
    """
    market_positions = [p for p in positions if p.pillar == "market"]
    if len(market_positions) < 2:
        return {"pairs": {}, "avg": None, "max": None}

    returns: dict[str, np.ndarray] = {}
    for p in market_positions:
        if p.asset in returns:
            continue
        r = fetch_returns(p.asset, timeframe=timeframe)
        if len(r) >= 24:  # need at least a day of bars to bother
            returns[p.asset] = r

    assets = sorted(returns.keys())
    pairs: dict[tuple[str, str], float] = {}
    triu_vals: list[float] = []
    for i, a in enumerate(assets):
        for b in assets[i + 1:]:
            ra, rb = returns[a], returns[b]
            n = min(len(ra), len(rb))
            if n < 24:
                continue
            ra2, rb2 = ra[-n:], rb[-n:]
            if np.std(ra2) == 0 or np.std(rb2) == 0:
                continue
            c = float(np.corrcoef(ra2, rb2)[0, 1])
            if math.isnan(c):
                continue
            pairs[(a, b)] = c
            triu_vals.append(c)

    return {
        "pairs": pairs,
        "avg": float(np.mean(triu_vals)) if triu_vals else None,
        "max": float(np.max(triu_vals)) if triu_vals else None,
    }


def parametric_var_cvar(
    positions: list[Position],
    confidence: float = 0.95,
    horizon_bars: int = 24,
) -> tuple[float, float]:
    """One-day parametric VaR and historical CVaR across the portfolio.

    Method:
      1. Pull 1h log returns for each market asset.
      2. Build weighted portfolio returns: w_i * sign(direction) where w_i is
         notional_usd / gross_exposure.
      3. Sum across positions per timestamp (intersection of available history).
      4. Scale daily by sqrt(horizon_bars) using returns std.
      5. VaR = -Z * sigma * gross_notional  (positive number = dollar loss).
      6. CVaR = mean of worst (1-confidence) tail of historical 1-bar P&L,
         scaled by sqrt(horizon_bars).

    Polymarket positions are not modeled — they have discrete binary payouts,
    not continuous returns. Phase B will add a separate binomial-stress for PM.
    """
    market_positions = [p for p in positions if p.pillar == "market"]
    gross = sum(abs(p.notional_usd) for p in market_positions)
    if gross <= 0 or not market_positions:
        return 0.0, 0.0

    # Map asset -> returns; positions can share an asset (multiple legs)
    cache: dict[str, np.ndarray] = {}
    for p in market_positions:
        if p.asset not in cache:
            r = fetch_returns(p.asset)
            cache[p.asset] = r if len(r) >= 24 else np.array([])

    # Trim to common length across assets with data
    nonempty = [r for r in cache.values() if len(r) > 0]
    if not nonempty:
        return 0.0, 0.0
    n = min(len(r) for r in nonempty)
    if n < 24:
        return 0.0, 0.0

    # Per-bar portfolio return = sum_i (w_i * sign_i * r_{i,t})
    port_returns = np.zeros(n)
    for p in market_positions:
        r = cache.get(p.asset)
        if r is None or len(r) < n:
            continue
        sign = +1 if p.direction in ("long", "yes") else -1
        weight = p.notional_usd / gross
        port_returns += weight * sign * r[-n:]

    sigma = float(np.std(port_returns))
    # Scale 1-bar (1h) sigma to horizon (24h ≈ 1d)
    sigma_horizon = sigma * math.sqrt(horizon_bars)
    z = _Z_95 if confidence >= 0.95 else 1.2816
    var_usd = z * sigma_horizon * gross

    # Historical CVaR — average of tail returns scaled to horizon
    sorted_r = np.sort(port_returns)
    tail_n = max(1, int((1 - confidence) * n))
    tail_mean = float(np.mean(sorted_r[:tail_n]))  # negative number
    # tail_mean is per-bar; scale to horizon
    cvar_usd = -tail_mean * math.sqrt(horizon_bars) * gross
    cvar_usd = max(cvar_usd, var_usd)  # CVaR >= VaR by construction

    return float(var_usd), float(cvar_usd)


def factor_exposures(positions: list[Position]) -> dict:
    """Coarse factor exposures across open positions.

    Stage 1: BTC-beta proxy (any position with 'BTC' in symbol is +1 beta),
    plus simple net long/short by pillar. Workstream 4 Phase B will replace
    this with regression betas vs (BTC, ETH, DXY, 10Y).
    """
    btc_long = sum(p.notional_usd for p in positions
                   if "BTC" in p.asset.upper() and p.direction in ("long", "yes"))
    btc_short = sum(p.notional_usd for p in positions
                    if "BTC" in p.asset.upper() and p.direction in ("short", "no"))
    net_market = sum(
        p.notional_usd * (1 if p.direction in ("long", "yes") else -1)
        for p in positions if p.pillar == "market"
    )
    return {
        "btc_proxy_long_usd": round(btc_long, 2),
        "btc_proxy_short_usd": round(btc_short, 2),
        "net_market_usd": round(net_market, 2),
    }


def load_open_positions() -> list[Position]:
    """Read trades.status='open' and project to Position objects.

    notional_usd = entry_price * quantity * (leverage or 1). For Polymarket
    bets we use sized_bet_usd from the polymarket_bets row.
    """
    from lib.db import get_connection
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT t.id, t.pillar, t.asset, t.direction,
                      t.entry_price, t.quantity, t.leverage,
                      pb.kelly_bet_size AS pm_size
                 FROM trades t
                 LEFT JOIN polymarket_bets pb ON pb.trade_id = t.id
                WHERE t.status = 'open'"""
        ).fetchall()
    finally:
        conn.close()
    positions: list[Position] = []
    for r in rows:
        if r["pillar"] == "polymarket":
            notional = float(r["pm_size"] or 0)
        else:
            qty = float(r["quantity"] or 0)
            entry = float(r["entry_price"] or 0)
            lev = float(r["leverage"] or 1)
            notional = qty * entry * lev
        if notional <= 0:
            continue
        positions.append(Position(
            asset=r["asset"],
            direction=r["direction"],
            notional_usd=notional,
            pillar=r["pillar"],
        ))
    return positions


def get_capital_usd() -> float:
    """Read the paper or live capital used as the denominator for VaR %."""
    try:
        from lib.db import get_connection, get_system_state
        conn = get_connection()
        try:
            cap = get_system_state(conn, "paper_balance")
            if cap is not None:
                return float(cap)
        finally:
            conn.close()
    except Exception:
        pass
    return float(os.environ.get("PAPER_STARTING_BALANCE", "500"))


def build_snapshot() -> RiskSnapshot:
    """Compute the full portfolio risk snapshot at this moment."""
    positions = load_open_positions()
    capital = get_capital_usd()
    gross = sum(abs(p.notional_usd) for p in positions)
    net = sum(
        p.notional_usd * (1 if p.direction in ("long", "yes") else -1)
        for p in positions
    )
    var_usd, cvar_usd = parametric_var_cvar(positions)
    corr = correlation_matrix(positions)
    factors = factor_exposures(positions)
    var_pct = (var_usd / capital * 100.0) if capital > 0 else 0.0
    return RiskSnapshot(
        snapshot_at=datetime.now(timezone.utc).isoformat(),
        capital_usd=capital,
        open_position_count=len(positions),
        gross_exposure_usd=round(gross, 2),
        net_exposure_usd=round(net, 2),
        var_95_1d_usd=round(var_usd, 2),
        cvar_95_1d_usd=round(cvar_usd, 2),
        var_95_pct=round(var_pct, 3),
        avg_pairwise_correlation=corr["avg"],
        max_pairwise_correlation=corr["max"],
        factor_exposures=factors,
    )


def persist_snapshot(snap: RiskSnapshot) -> int:
    """Insert the snapshot into portfolio_risk_snapshots + correlation rows."""
    from lib.db import get_connection
    conn = get_connection()
    try:
        row = snap.to_db_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        cur = conn.execute(
            f"INSERT INTO portfolio_risk_snapshots ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        snap_id = cur.lastrowid
        conn.commit()
        return snap_id
    finally:
        conn.close()


def persist_correlation_matrix(pairs: dict, window_days: int = 7) -> int:
    """Idempotent per-day write of pairwise correlations."""
    if not pairs:
        return 0
    from lib.db import get_connection
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection()
    n = 0
    try:
        for (a, b), c in pairs.items():
            conn.execute(
                """INSERT OR REPLACE INTO correlation_matrix_daily
                       (date, asset_a, asset_b, correlation, window_days)
                   VALUES (?, ?, ?, ?, ?)""",
                (today, a, b, c, window_days),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


if __name__ == "__main__":
    snap = build_snapshot()
    print(f"capital=${snap.capital_usd:,.2f}")
    print(f"open_positions={snap.open_position_count}")
    print(f"gross_exposure=${snap.gross_exposure_usd:,.2f}")
    print(f"net_exposure=${snap.net_exposure_usd:,.2f}")
    print(f"VaR_95_1d=${snap.var_95_1d_usd:,.2f}  ({snap.var_95_pct:.2f}% of capital)")
    print(f"CVaR_95_1d=${snap.cvar_95_1d_usd:,.2f}")
    if snap.avg_pairwise_correlation is not None:
        print(f"avg pairwise corr={snap.avg_pairwise_correlation:.3f}, max={snap.max_pairwise_correlation:.3f}")
    print(f"factors={snap.factor_exposures}")
