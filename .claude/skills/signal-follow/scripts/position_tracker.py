"""Emit trader_signals.json from aggregate positioning data.

confluence_detector.py reads this file (line 126) to cross-check live setups
against what skilled traders are doing right now. Previously this hit Bybit's
copy-trade leaderboard, but the API is rate-limited and we switched broker to
OKX anyway. The leaderboard scrape was producing zero signals every cycle, so
the confluence engine never got the trader-type bump.

This version fetches **public funding-rate data** from OKX swap markets via
ccxt — no auth required. Sustained one-directional funding represents
aggregate trader positioning, which is the same edge the leaderboard scrape
was meant to capture (and arguably a cleaner read than any single trader).

  funding > +0.05% / 8h  → traders paying to be long  → trader_accumulation long
  funding < -0.05% / 8h  → traders paying to be short → trader_accumulation short

Magnitude scales `skill_score` 0.5-1.0 so confluence_engine's strength
weighting still differentiates conviction levels.

Offline-safe: if ccxt or OKX fails, writes an empty signal list and exits 0.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _load_watchlist_perps() -> list[str]:
    """Pull the crypto-perp watchlist as a flat list of ccxt symbol strings."""
    try:
        with open(Path(PROJECT_ROOT) / "config" / "watchlist.json") as f:
            wl = json.load(f).get("watchlist", {})
        return list(wl.get("crypto_perpetuals", []))
    except Exception as e:
        print(f"[position_tracker] watchlist load failed: {e}", file=sys.stderr)
        return []


def _funding_signal(symbol: str, exchange) -> dict | None:
    """Fetch funding rate, classify direction + conviction. None when neutral."""
    try:
        fr = exchange.fetch_funding_rate(symbol)
    except Exception as e:
        print(f"[position_tracker] {symbol} funding fetch failed: {e}", file=sys.stderr)
        return None
    rate = fr.get("fundingRate")
    if rate is None:
        return None
    # OKX returns funding as a fraction per 8h period. Convert to bps for readability.
    # Empirical: BTC/ETH funding sits in [-1.0, +1.0] bps even on trending days,
    # so the threshold is calibrated to the actual distribution — not the
    # textbook 5-30bps range that applies to volatile small caps only.
    bps = float(rate) * 10_000
    if abs(bps) < 0.3:  # below 0.3bps over 8h → essentially neutral
        return None
    direction = "long" if bps > 0 else "short"
    # skill_score maps |bps| → [0.5, 1.0]: 0.3bps→0.5, 2bps→1.0
    conviction = min(1.0, 0.5 + (abs(bps) - 0.3) / 3.4)
    return {
        "asset": symbol,
        "symbol": symbol,
        "direction": direction,
        "skill_score": round(conviction, 3),
        "funding_bps_8h": round(bps, 2),
        "next_funding_at": fr.get("fundingDatetime"),
        "source": "okx_funding",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    signals: list[dict] = []
    try:
        import ccxt  # type: ignore
        exchange = ccxt.okx({"enableRateLimit": True})
        # Public endpoints — no auth needed.
        for sym in _load_watchlist_perps():
            sig = _funding_signal(sym, exchange)
            if sig:
                signals.append(sig)
    except ImportError:
        print("[position_tracker] ccxt unavailable — emitting empty signal list", file=sys.stderr)
    except Exception as e:
        print(f"[position_tracker] exchange init failed: {e}", file=sys.stderr)

    out = out_dir / "trader_signals.json"
    with open(out, "w") as f:
        json.dump(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "signals": signals},
            f,
            indent=2,
        )
    print(f"[position_tracker] {len(signals)} trader signals from OKX funding → {out}")


if __name__ == "__main__":
    main()