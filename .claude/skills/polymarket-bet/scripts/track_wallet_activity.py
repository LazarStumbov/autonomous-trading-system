"""Layer 2: poll tracked wallets for new entries since last run.

Writes data/signals/<date>/pm_wallet_activity.json with:
  - new_entries: list of activities since last poll, enriched with wallet meta
  - cluster_signals: markets where 2+ tracked wallets entered within 30 min
  - conviction_signals: bets that are large vs the wallet's median size

State (last poll timestamp per wallet) lives in data/memory/pm_wallet_state.json.

No LLM. Fast Data API polls only.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
CONFIG_PATH = ROOT / "config" / "polymarket_accounts.json"
STATE_PATH = ROOT / "data" / "memory" / "pm_wallet_state.json"
SIGNALS_DIR = ROOT / "data" / "signals"

CLUSTER_WINDOW_SECONDS = 1800  # 30 minutes


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _ts_of(activity: dict) -> int:
    ts = activity.get("timestamp")
    if isinstance(ts, (int, float)):
        return int(ts)
    if isinstance(ts, str):
        try:
            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return 0
    return 0


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def main() -> int:
    if not CONFIG_PATH.exists():
        print("[track_wallet_activity] no config — skipping")
        return 0
    cfg = json.loads(CONFIG_PATH.read_text())
    tracked = cfg.get("tracked_accounts", [])
    if not tracked:
        print("[track_wallet_activity] tracked_accounts empty — run discover_wallets.py first")
        return 0

    state = _load_state()
    now_ts = _now()
    cutoff_default = now_ts - 3600  # default lookback 1h

    wallet_meta = {w["wallet"]: w for w in tracked}

    new_entries: list[dict] = []
    for w in tracked:
        wallet = w["wallet"]
        since = state.get(wallet, cutoff_default)
        try:
            since_int = int(since)
        except (TypeError, ValueError):
            since_int = cutoff_default
        activity = pm_api.get_wallet_activity(wallet, limit=50, since_ts=since_int)
        if not activity:
            state[wallet] = now_ts
            continue
        for a in activity:
            ts = _ts_of(a)
            if ts <= since_int:
                continue
            size = _safe_float(a.get("size") or a.get("usdcSize") or a.get("amount"))
            new_entries.append({
                "wallet": wallet,
                "cluster_id": w.get("cluster_id"),
                "skill_score": w.get("skill_score"),
                "market_id": a.get("marketId") or a.get("conditionId"),
                "market_question": a.get("title") or a.get("question") or a.get("eventTitle"),
                "outcome": a.get("outcome") or a.get("side"),
                "size_usd": size,
                "price": _safe_float(a.get("price")),
                "ts": ts,
                "raw": {k: a.get(k) for k in ("type", "txHash", "timestamp")},
            })
        state[wallet] = now_ts

    # Cluster signals: same market_id with 2+ wallets within 30min
    by_market: dict[str, list[dict]] = defaultdict(list)
    for e in new_entries:
        if e["market_id"]:
            by_market[e["market_id"]].append(e)

    cluster_signals: list[dict] = []
    for mid, entries in by_market.items():
        if len(entries) < 2:
            continue
        entries.sort(key=lambda x: x["ts"])
        # Sliding window of 30 minutes
        i = 0
        while i < len(entries):
            j = i
            window = [entries[i]]
            while j + 1 < len(entries) and entries[j + 1]["ts"] - entries[i]["ts"] <= CLUSTER_WINDOW_SECONDS:
                window.append(entries[j + 1])
                j += 1
            unique_wallets = {e["wallet"] for e in window}
            unique_clusters = {e["cluster_id"] for e in window if e.get("cluster_id")}
            if len(unique_wallets) >= 2 and len(unique_clusters) >= 2:
                cluster_signals.append({
                    "market_id": mid,
                    "market_question": window[0].get("market_question"),
                    "outcome": window[0].get("outcome"),
                    "wallets": list(unique_wallets),
                    "clusters": list(unique_clusters),
                    "wallet_count": len(unique_wallets),
                    "total_size_usd": sum(e["size_usd"] for e in window),
                    "first_ts": window[0]["ts"],
                    "last_ts": window[-1]["ts"],
                })
                i = j + 1
            else:
                i += 1

    # Conviction signals: bet > 2x wallet's median size from features
    conviction_signals: list[dict] = []
    for e in new_entries:
        meta = wallet_meta.get(e["wallet"], {})
        # We don't have median per-wallet stored; use a proxy: bet > $5k = high conviction
        # (median is recomputed weekly in discover_wallets but not persisted)
        if e["size_usd"] >= 5000:
            conviction_signals.append({
                "wallet": e["wallet"],
                "cluster_id": e["cluster_id"],
                "market_id": e["market_id"],
                "market_question": e["market_question"],
                "outcome": e["outcome"],
                "size_usd": e["size_usd"],
                "skill_score": meta.get("skill_score"),
                "ts": e["ts"],
            })

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = SIGNALS_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pm_wallet_activity.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_entry_count": len(new_entries),
        "cluster_signal_count": len(cluster_signals),
        "conviction_signal_count": len(conviction_signals),
        "new_entries": new_entries,
        "cluster_signals": cluster_signals,
        "conviction_signals": conviction_signals,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    _save_state(state)
    print(
        f"[track_wallet_activity] entries={len(new_entries)} clusters={len(cluster_signals)} "
        f"conviction={len(conviction_signals)} → {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
