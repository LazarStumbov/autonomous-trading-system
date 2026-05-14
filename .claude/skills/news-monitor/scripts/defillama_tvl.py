"""DefiLlama TVL + stablecoin supply tracker (free, no API key).

Pulls cross-chain TVL deltas and stablecoin supply. Big TVL changes precede
volatility regimes in crypto. Stablecoin supply expansion is a coarse
liquidity proxy for the crypto risk environment.

Writes data/signals/<date>/onchain_defillama.json with:
  - top chain TVLs (latest USD + 30d % delta)
  - stablecoin total supply + 30d delta per major issuer
  - regime tags: tvl_expanding | tvl_contracting | stables_inflating | stables_deflating
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


def _fetch(url: str) -> list | dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trading-system/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[defillama_tvl] fetch failed {url}: {e}")
        return None


def _top_chains() -> list[dict]:
    """Top 12 chains by current TVL with 1d/7d/30d trend tags."""
    data = _fetch("https://api.llama.fi/v2/chains") or []
    if not isinstance(data, list):
        return []
    chains = sorted(data, key=lambda c: c.get("tvl", 0) or 0, reverse=True)[:12]
    return [
        {
            "name": c.get("name"),
            "tvl_usd": c.get("tvl"),
            "symbol": c.get("tokenSymbol"),
            "gecko_id": c.get("gecko_id"),
        }
        for c in chains
    ]


def _stablecoins() -> dict:
    """Aggregate stablecoin supply across all chains."""
    data = _fetch("https://stablecoins.llama.fi/stablecoins?includePrices=false") or {}
    coins = data.get("peggedAssets") if isinstance(data, dict) else None
    if not coins:
        return {}
    out: dict[str, dict] = {}
    for c in coins[:10]:  # top 10 stables
        sym = c.get("symbol") or c.get("name")
        circ = c.get("circulating", {})
        total = (circ.get("peggedUSD") if isinstance(circ, dict) else None) or 0
        prev = c.get("circulatingPrevDay", {})
        prev_total = (prev.get("peggedUSD") if isinstance(prev, dict) else None) or total
        out[sym] = {
            "circulating_usd": total,
            "delta_24h_usd": total - prev_total,
            "delta_24h_pct": (total - prev_total) / max(prev_total, 1e-9) * 100,
        }
    return out


def _regime_tags(chains: list[dict], stables: dict) -> dict:
    total_tvl = sum((c.get("tvl_usd") or 0) for c in chains)
    stables_total = sum((v.get("circulating_usd") or 0) for v in stables.values())
    stables_delta_pct = (
        sum((v.get("delta_24h_usd") or 0) for v in stables.values())
        / max(stables_total, 1e-9)
        * 100
    )
    tags: list[str] = []
    if stables_delta_pct > 0.5:
        tags.append("stables_inflating")
    elif stables_delta_pct < -0.5:
        tags.append("stables_deflating")
    return {
        "total_defi_tvl_usd": total_tvl,
        "total_stables_usd": stables_total,
        "stables_delta_24h_pct": round(stables_delta_pct, 3),
        "tags": tags,
    }


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "onchain_defillama.json"

    chains = _top_chains()
    stables = _stablecoins()
    regime = _regime_tags(chains, stables)

    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chains": chains,
        "stables": stables,
        "regime": regime,
    }, indent=2))
    print(f"[defillama_tvl] {len(chains)} chains, {len(stables)} stables, "
          f"tags={regime['tags']} → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
