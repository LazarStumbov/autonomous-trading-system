"""Layer 1 (weekly): pull leaderboard, score wallets, cluster, write to config.

Runs Sunday via the weekly cron. Side-effect-only: rewrites
`config/polymarket_accounts.json::tracked_accounts` and `wallet_clusters`.

Pipeline:
  1. Pull top traders from Data API leaderboard (month + all-time).
  2. Pull each candidate's recent activity to compute features.
  3. Filter out bot-suspect wallets (high-frequency, near-50/50 split).
  4. Score with the formula already in the config (win_rate weighted).
  5. Apply Bayesian shrinkage to penalize low-N wallets.
  6. Cluster by funding-source proxy + entry-timing correlation.
  7. Write top-25 to config.

No LLM. Pure on-chain/leaderboard analytics.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
CONFIG_PATH = ROOT / "config" / "polymarket_accounts.json"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _wallet_features(wallet: str) -> dict:
    """Pull recent activity and derive bet features for scoring."""
    activity = pm_api.get_wallet_activity(wallet, limit=200)
    if not activity:
        return {"activity_count": 0}

    sizes: list[float] = []
    timestamps: list[int] = []
    yes_count = 0
    no_count = 0
    market_set: set[str] = set()
    categories: list[str] = []

    for a in activity:
        sizes.append(_safe_float(a.get("size") or a.get("usdcSize") or a.get("amount")))
        ts = a.get("timestamp")
        if isinstance(ts, (int, float)):
            timestamps.append(int(ts))
        elif isinstance(ts, str):
            try:
                timestamps.append(int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()))
            except ValueError:
                pass
        outcome = (a.get("outcome") or a.get("side") or "").lower()
        if "yes" in outcome or outcome == "buy":
            yes_count += 1
        elif "no" in outcome or outcome == "sell":
            no_count += 1
        if a.get("marketId") or a.get("conditionId"):
            market_set.add(a.get("marketId") or a.get("conditionId"))
        cat = a.get("category") or a.get("eventCategory")
        if cat:
            categories.append(cat.lower())

    median_size = sorted(sizes)[len(sizes) // 2] if sizes else 0
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    # Holding period proxy: median time between consecutive trades
    holding_seconds = 0
    if len(timestamps) >= 2:
        timestamps.sort()
        gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
        gaps.sort()
        holding_seconds = gaps[len(gaps) // 2]

    yes_no_split = abs((yes_count - no_count) / max(yes_count + no_count, 1))
    last_active = max(timestamps) if timestamps else 0

    return {
        "activity_count": len(activity),
        "median_size": median_size,
        "avg_size": avg_size,
        "median_holding_seconds": holding_seconds,
        "yes_no_split": yes_no_split,  # 0=balanced, 1=fully directional
        "unique_markets": len(market_set),
        "categories": list({c for c in categories}),
        "last_active_ts": last_active,
        "_market_ids": list(market_set),
        "_timestamps": timestamps,
    }


def _is_bot_suspect(features: dict) -> bool:
    """Flag wallets that look like market makers / HFT bots, not directional traders."""
    if features.get("activity_count", 0) >= 500:
        return True
    if 0 < features.get("median_holding_seconds", 0) < 60:
        return True
    # Near-50/50 yes/no split with high volume = MM
    if features.get("activity_count", 0) > 50 and features.get("yes_no_split", 1) < 0.1:
        return True
    return False


def _score_wallet(lb_entry: dict, features: dict, weights: dict) -> float:
    """Composite skill score in [0, 1] before Bayesian shrinkage."""
    win_rate = _safe_float(lb_entry.get("winRate") or lb_entry.get("win_rate"))
    if win_rate > 1:
        win_rate = win_rate / 100.0

    # Consistency = inverse of yes/no oscillation (we want directional players)
    consistency = features.get("yes_no_split", 0)

    # Diversity = ln-scaled unique markets (capped at ~50)
    diversity = min(math.log(1 + features.get("unique_markets", 0)) / math.log(51), 1.0)

    # Conviction sizing = avg_size / median_size (whales swing bigger sometimes)
    avg = features.get("avg_size", 0)
    med = max(features.get("median_size", 1), 1)
    conviction = min(avg / med, 3.0) / 3.0

    # Recency: 1 if active in last 7d, 0 if > 30d ago
    last = features.get("last_active_ts", 0)
    if last:
        age_days = (datetime.now(timezone.utc).timestamp() - last) / 86400
        recency = max(0, 1 - age_days / 30)
    else:
        recency = 0

    score = (
        weights.get("win_rate", 0.35) * win_rate
        + weights.get("consistency", 0.25) * consistency
        + weights.get("category_diversity", 0.15) * diversity
        + weights.get("conviction_sizing", 0.15) * conviction
        + weights.get("recency", 0.10) * recency
    )
    return max(0.0, min(1.0, score))


def _bayesian_shrink(score: float, n_positions: int, prior: float = 0.5, prior_strength: int = 50) -> float:
    """Pull score toward prior when we have few observations."""
    return (n_positions * score + prior_strength * prior) / max(n_positions + prior_strength, 1)


def _cluster_wallets(scored: list[dict]) -> list[dict]:
    """Group wallets that look like the same entity behind multiple addresses.

    Heuristic v1: cluster wallets that overlap on >= 5 markets AND have entry
    timing within 2 hours on those overlaps. This catches the Théo signature
    where one operator splits stakes across many wallets.
    """
    if len(scored) < 2:
        return [{"id": f"C-{i:03d}", "wallets": [w["wallet"]], "size": 1} for i, w in enumerate(scored)]

    # Build {market_id: [(wallet, ts), ...]}
    market_index = defaultdict(list)
    for w in scored:
        for mid, ts in zip(w["_market_ids"], w["_timestamps"][: len(w["_market_ids"])]):
            market_index[mid].append((w["wallet"], ts))

    # Pairwise overlap counts
    pair_overlap: dict[tuple[str, str], int] = defaultdict(int)
    for entries in market_index.values():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                w1, t1 = entries[i]
                w2, t2 = entries[j]
                if w1 == w2:
                    continue
                if abs(t1 - t2) <= 7200:  # 2h
                    key = (min(w1, w2), max(w1, w2))
                    pair_overlap[key] += 1

    # Union-find clustering on pairs with >= 5 overlaps
    parent: dict[str, str] = {w["wallet"]: w["wallet"] for w in scored}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for (a, b), count in pair_overlap.items():
        if count >= 5:
            union(a, b)

    groups: dict[str, list[str]] = defaultdict(list)
    for w in scored:
        groups[find(w["wallet"])].append(w["wallet"])

    return [
        {"id": f"C-{i:03d}", "wallets": members, "size": len(members)}
        for i, members in enumerate(sorted(groups.values(), key=len, reverse=True))
    ]


def main() -> int:
    cfg = _load_config()
    discovery = cfg.get("discovery", {})
    weights = cfg.get("scoring_weights", {})
    max_tracked = int(discovery.get("max_tracked", 25))
    min_positions = int(discovery.get("min_positions", 20))
    min_win_rate = _safe_float(discovery.get("min_win_rate", 0.55))
    min_profit = _safe_float(discovery.get("min_profit_usd", 1000))

    # Pull leaderboard windows; merge by wallet
    candidates: dict[str, dict] = {}
    for window in ("month", "all"):
        for entry in pm_api.get_leaderboard(period=window, limit=100):
            wallet = entry.get("proxyWallet") or entry.get("wallet") or entry.get("address")
            if not wallet:
                continue
            existing = candidates.get(wallet, {})
            existing.update(entry)
            candidates[wallet] = existing

    print(f"[discover_wallets] leaderboard candidates: {len(candidates)}")
    if not candidates:
        print("[discover_wallets] empty leaderboard — skipping write")
        return 0

    # Seed wallets bypass the coarse filter — they're manually curated.
    seed_wallets = {w.lower() for w in (cfg.get("seed_wallets") or [])}

    # Filter on raw thresholds before paying for activity pulls
    coarse_filtered: list[tuple[str, dict]] = []
    for wallet, entry in candidates.items():
        if wallet.lower() in seed_wallets:
            coarse_filtered.append((wallet, entry))
            continue
        win_rate = _safe_float(entry.get("winRate") or entry.get("win_rate"))
        if win_rate > 1:
            win_rate = win_rate / 100.0
        positions = int(_safe_float(entry.get("totalTrades") or entry.get("trades") or entry.get("totalPositions")))
        profit = _safe_float(entry.get("profit") or entry.get("pnl") or entry.get("netPnl"))
        if positions >= min_positions and win_rate >= min_win_rate and profit >= min_profit:
            coarse_filtered.append((wallet, entry))

    print(f"[discover_wallets] passed coarse filter: {len(coarse_filtered)}")
    # Cap on activity pulls for cost discipline (one pull per wallet)
    coarse_filtered = coarse_filtered[: max(max_tracked * 3, 50)]

    scored: list[dict] = []
    for wallet, entry in coarse_filtered:
        features = _wallet_features(wallet)
        if features.get("activity_count", 0) < min_positions:
            continue
        if _is_bot_suspect(features):
            continue
        raw = _score_wallet(entry, features, weights)
        adj = _bayesian_shrink(raw, features["activity_count"])
        scored.append({
            "wallet": wallet,
            "raw_score": round(raw, 4),
            "skill_score": round(adj, 4),
            "pnl_30d_usd": round(_safe_float(entry.get("profit") or entry.get("pnl")), 2),
            "win_rate": round(_safe_float(entry.get("winRate") or entry.get("win_rate")) / (100 if _safe_float(entry.get("winRate") or 0) > 1 else 1), 4),
            "total_positions": features["activity_count"],
            "categories": features["categories"][:5],
            "is_bot_suspect": False,
            "last_active_iso": datetime.fromtimestamp(features["last_active_ts"], tz=timezone.utc).isoformat() if features.get("last_active_ts") else None,
            "_market_ids": features["_market_ids"],
            "_timestamps": features["_timestamps"],
        })

    scored.sort(key=lambda x: x["skill_score"], reverse=True)
    top = scored[:max_tracked]

    clusters = _cluster_wallets(top)
    cluster_lookup = {w: c["id"] for c in clusters for w in c["wallets"]}

    # Strip private fields and attach cluster IDs
    tracked_out = []
    for w in top:
        public = {k: v for k, v in w.items() if not k.startswith("_")}
        public["cluster_id"] = cluster_lookup.get(w["wallet"], "C-???")
        public["label"] = f"{public['cluster_id']}-{w['wallet'][:6]}"
        tracked_out.append(public)

    cfg["tracked_accounts"] = tracked_out
    cfg["wallet_clusters"] = [{"id": c["id"], "wallets": c["wallets"], "size": c["size"]} for c in clusters if c["size"] >= 1]
    cfg["last_refreshed"] = datetime.now(timezone.utc).isoformat()
    _save_config(cfg)

    multi = sum(1 for c in clusters if c["size"] > 1)
    print(f"[discover_wallets] wrote {len(tracked_out)} tracked + {multi} multi-wallet clusters → {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
