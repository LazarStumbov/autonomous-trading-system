"""Layer 2: aggregate all signals into a ranked candidate list.

Reads:
  data/signals/<date>/pm_markets.json
  data/signals/<date>/pm_wallet_activity.json
  data/signals/<date>/news_*.json    (best-effort; news-monitor outputs)

Writes:
  data/signals/<date>/pm_candidates.json

Each candidate has a confluence_score in [0, 100] and a `reasons` array
explaining which signals contributed. Threshold = 60 to pass to Layer 3.

No LLM. Pure heuristics.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
SIGNALS_DIR = ROOT / "data" / "signals"


def _threshold() -> float:
    """60 in production; in paper mode, lower to flow more candidates to LLM research."""
    if os.environ.get("PAPER_MODE", "").lower() != "true":
        return 60.0
    try:
        with open(ROOT / "config" / "risk_params.json") as f:
            cfg = json.load(f)
        return float(cfg.get("paper_mode_overrides", {}).get("polymarket_min_confluence_score", 60))
    except Exception:
        return 60.0


THRESHOLD = _threshold()


def _today_dir() -> Path:
    return SIGNALS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _market_index(markets: list[dict]) -> dict[str, dict]:
    idx = {}
    for m in markets:
        if m.get("id"):
            idx[m["id"]] = m
        if m.get("condition_id"):
            idx[m["condition_id"]] = m
    return idx


def _smart_money_signals(activity: dict | None) -> dict[str, dict]:
    """Build per-market smart-money score components."""
    out: dict[str, dict] = defaultdict(lambda: {
        "single_sharp_count": 0,
        "cluster_signal": False,
        "high_conviction_count": 0,
        "wallets": set(),
        "outcome": None,
    })
    if not activity:
        return out

    for entry in activity.get("new_entries", []):
        mid = entry.get("market_id")
        if not mid:
            continue
        bucket = out[mid]
        bucket["single_sharp_count"] += 1
        bucket["wallets"].add(entry.get("wallet"))
        if not bucket["outcome"]:
            bucket["outcome"] = entry.get("outcome")

    for cs in activity.get("cluster_signals", []):
        mid = cs.get("market_id")
        if mid:
            out[mid]["cluster_signal"] = True
            out[mid]["wallet_count_in_cluster"] = cs.get("wallet_count", 0)
            if not out[mid].get("outcome"):
                out[mid]["outcome"] = cs.get("outcome")

    for cv in activity.get("conviction_signals", []):
        mid = cv.get("market_id")
        if mid:
            out[mid]["high_conviction_count"] += 1

    # Convert sets to lists for JSON
    for v in out.values():
        v["wallets"] = list(v["wallets"])
    return out


def _late_stage_score(market: dict) -> tuple[int, str | None]:
    yes = market.get("yes_price") or 0
    hours = market.get("hours_to_resolution", 1e9)
    liq = market.get("liquidity_usd", 0)
    if 0.90 <= yes <= 0.97 and 24 <= hours <= 168 and liq >= 50_000:
        return 25, f"late-stage: yes={yes:.2f}, resolves in {hours:.0f}h, liq=${liq:,.0f}"
    return 0, None


def _obscure_market_score(market: dict) -> tuple[int, str | None]:
    liq = market.get("liquidity_usd", 0)
    vol = market.get("volume_24h_usd", 0)
    if 10_000 <= liq <= 50_000 and vol >= 1_000:
        return 10, f"obscure-growing: liq=${liq:,.0f}, 24h vol=${vol:,.0f}"
    return 0, None


def _news_signals(today: Path) -> dict[str, dict]:
    """Best-effort: scan news-monitor outputs for items relevant to PM markets.

    news-monitor doesn't tag PM markets, so we match on keyword overlap with
    the market question. v1 is loose; future tightening if FP rate is high.
    """
    out: dict[str, list[dict]] = defaultdict(list)
    for fname in ("news_setups.json", "urgency_alerts.json", "news_aggregated.json"):
        p = today / fname
        data = _load(p)
        if not data:
            continue
        items = data if isinstance(data, list) else data.get("items") or data.get("alerts") or []
        for it in items:
            urgency = it.get("urgency") or it.get("urgency_score") or 0
            if urgency >= 7:
                out["_high_urgency_items"].append(it)
    return out


def _has_news_match(market: dict, news_items: list[dict]) -> dict | None:
    if not news_items:
        return None
    q = (market.get("question") or "").lower()
    if not q:
        return None
    q_words = {w for w in q.split() if len(w) > 4}
    for item in news_items:
        text = " ".join(str(item.get(k, "")) for k in ("headline", "title", "summary", "text")).lower()
        if not text:
            continue
        text_words = set(text.split())
        if len(q_words & text_words) >= 3:
            return item
    return None


def _cross_market_inconsistency(markets: list[dict]) -> dict[str, dict]:
    """Detect logical inconsistencies between related markets.

    v1 heuristic: group by event slug prefix (markets sharing a slug root often
    represent the same event); flag groups where Σ yes_price > 1.05 or < 0.95.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for m in markets:
        slug = m.get("slug") or ""
        # crude root: first 3 dash-separated tokens
        root = "-".join(slug.split("-")[:3])
        if root:
            grouped[root].append(m)
    inconsistencies: dict[str, dict] = {}
    for root, group in grouped.items():
        if len(group) < 2:
            continue
        total = sum((m.get("yes_price") or 0) for m in group)
        if total > 1.05 or total < 0.95:
            for m in group:
                inconsistencies[m["id"]] = {
                    "group_root": root,
                    "group_size": len(group),
                    "sum_yes": round(total, 3),
                    "deviation": round(total - 1, 3),
                }
    return inconsistencies


def main() -> int:
    today = _today_dir()
    today.mkdir(parents=True, exist_ok=True)

    markets_payload = _load(today / "pm_markets.json")
    if not markets_payload:
        print("[signal_engine] no markets snapshot — run discover_markets.py first")
        return 0
    markets = markets_payload.get("markets", [])

    activity = _load(today / "pm_wallet_activity.json")
    sm_signals = _smart_money_signals(activity)

    news_data = _news_signals(today)
    high_urgency = news_data.get("_high_urgency_items", [])

    inconsistencies = _cross_market_inconsistency(markets)

    candidates: list[dict] = []
    for m in markets:
        score = 0
        reasons: list[str] = []
        signals: dict = {}

        # Smart money
        sm = sm_signals.get(m["id"]) or sm_signals.get(m.get("condition_id"))
        if sm:
            if sm.get("cluster_signal"):
                score += 30
                reasons.append(f"cluster signal: {sm.get('wallet_count_in_cluster', 0)} sharps converging")
                signals["cluster"] = sm
            elif sm.get("single_sharp_count", 0) >= 1:
                pts = min(15, 8 + sm["single_sharp_count"] * 3)
                score += pts
                reasons.append(f"smart-money entry x{sm['single_sharp_count']}")
                signals["smart_money"] = sm
            if sm.get("high_conviction_count", 0) >= 1:
                score += 15
                reasons.append(f"high-conviction sizing x{sm['high_conviction_count']}")

        # Late-stage convergence
        late_pts, late_reason = _late_stage_score(m)
        if late_pts:
            score += late_pts
            reasons.append(late_reason)
            signals["late_stage"] = True

        # Obscure-growing
        obs_pts, obs_reason = _obscure_market_score(m)
        if obs_pts:
            score += obs_pts
            reasons.append(obs_reason)
            signals["obscure"] = True

        # News reprice
        news_match = _has_news_match(m, high_urgency)
        if news_match:
            score += 20
            reasons.append(f"news-urgency match: {news_match.get('headline') or news_match.get('title')}")
            signals["news"] = news_match

        # Cross-market inconsistency
        if m["id"] in inconsistencies:
            inc = inconsistencies[m["id"]]
            score += 20
            reasons.append(f"cross-market inconsistency: Σyes={inc['sum_yes']} (deviation {inc['deviation']:+.2f})")
            signals["inconsistency"] = inc

        # Fee-free bonus (concentrate edge where there's no fee drag)
        if m.get("fee_free"):
            score += 5
            reasons.append("fee-free geopolitical (rebate concentration)")

        if score <= 0:
            continue

        candidates.append({
            "market_id": m["id"],
            "market_question": m["question"],
            "yes_price": m["yes_price"],
            "liquidity_usd": m["liquidity_usd"],
            "volume_24h_usd": m["volume_24h_usd"],
            "categories": m.get("categories", []),
            "fee_free": m.get("fee_free", False),
            "hours_to_resolution": m["hours_to_resolution"],
            "clob_token_ids": m.get("clob_token_ids"),
            "confluence_score": min(score, 100),
            "passes_threshold": score >= THRESHOLD,
            "reasons": reasons,
            "signals": signals,
            # Suggested side: prefer smart-money outcome, else "yes" if late-stage, else "yes"
            "suggested_outcome": (sm or {}).get("outcome") or ("yes" if late_pts else "yes"),
        })

    candidates.sort(key=lambda x: x["confluence_score"], reverse=True)

    out_path = today / "pm_candidates.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold": THRESHOLD,
        "candidate_count": len(candidates),
        "passing_count": sum(1 for c in candidates if c["passes_threshold"]),
        "candidates": candidates,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(
        f"[signal_engine] candidates={len(candidates)} "
        f"passing(≥{THRESHOLD})={payload['passing_count']} → {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
