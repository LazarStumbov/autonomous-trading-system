"""Layer 3: Perplexity-gated probability estimation.

Reads pm_candidates.json. For each candidate above the confluence threshold:
  1. Check the 24h research cache → cache hit means zero LLM cost.
  2. On miss, call lib.perplexity.ask_safe() with a templated prompt.
  3. Parse the answer into structured fields (point estimate + band + base rate).
  4. Apply confidence-band shrinkage if the band is wide.
  5. Force NO_BET on insider-suspect categories (DOJ legal risk).
  6. Hard cap: max 10 LLM calls per cycle, ranked by confluence score.

Writes data/signals/<date>/pm_estimates.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib import perplexity  # noqa: E402

SIGNALS_DIR = ROOT / "data" / "signals"
CACHE_PATH = ROOT / "data" / "memory" / "pm_research_cache.json"

CACHE_TTL_HOURS = 24
MAX_LLM_CALLS_PER_CYCLE = int(os.environ.get("PM_MAX_LLM_CALLS", "10"))

# DOJ-flagged insider-risk markets — categories where classified info confers
# advantage. Force NO_BET regardless of edge to avoid legal exposure.
INSIDER_SUSPECT_KEYWORDS = [
    "military operation",
    "classified",
    "special forces",
    "covert",
    "intelligence agency",
    "fbi raid",
    "indictment of",
    "doj investigation",
]

SYSTEM_PROMPT = (
    "You are a calibrated forecaster. Return JSON only, no prose. "
    "Schema: {\"p\": <float 0-1>, \"low\": <float 0-1>, \"high\": <float 0-1>, "
    "\"base_rate\": <float 0-1>, \"key_factors\": [<3-5 short strings>]}."
)


def _today_dir() -> Path:
    return SIGNALS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _is_fresh(entry: dict) -> bool:
    ts = entry.get("ts")
    if not ts:
        return False
    try:
        cached_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
    return age_hours < entry.get("ttl_hours", CACHE_TTL_HOURS)


def _is_insider_suspect(question: str, categories: list[str]) -> bool:
    blob = (question or "").lower() + " " + " ".join(categories or []).lower()
    return any(kw in blob for kw in INSIDER_SUSPECT_KEYWORDS)


def _parse_answer(answer: str) -> dict | None:
    """Extract JSON from a Perplexity answer. Falls back to regex on common stray prose."""
    if not answer:
        return None
    # Strip code fences
    cleaned = answer.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back: greedy braces
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _shrink_to_market(p: float, low: float, high: float, market_price: float) -> float:
    """If our band is wide, regress toward the market price."""
    band = max(0, high - low)
    if band > 0.20:
        return 0.5 * p + 0.5 * market_price
    return p


def _has_wallet_evidence(cand: dict) -> bool:
    """Did signal_engine flag any smart-money or news evidence on this candidate?

    Anything sourced from wallet activity (cluster/single_sharp) or curated
    news urgency counts; pure late-stage / obscure / cross-market score
    components do NOT — those are price-pattern heuristics, not external evidence.
    """
    signals = cand.get("signals") or {}
    if signals.get("cluster") or signals.get("smart_money"):
        return True
    if signals.get("news"):
        return True
    return False


def _paper_heuristic_estimate(cand: dict, market_price: float) -> dict | None:
    """Paper-mode-only fallback when Perplexity is unavailable.

    Gated to candidates with either confluence>=80 OR wallet evidence.
    Without one of those, synthesising an edge produces Aston Villa
    nonsense: a 0.0015 YES priced at a tiny synthetic edge.

    Returns None if the candidate doesn't merit any synthetic estimate.
    Also kills extreme-tail markets (price <5% or >95%) absent wallet evidence —
    these are exactly the Aston Villa pattern.
    """
    if os.environ.get("PAPER_MODE", "").lower() != "true":
        return None
    conf = float(cand.get("confluence_score") or 0)
    has_evidence = _has_wallet_evidence(cand)

    # Hard gate: confluence>=80 OR wallet evidence required.
    if conf < 80 and not has_evidence:
        return None

    # Extreme-tail veto: if market price is in [0.05, 0.95] tails without
    # explicit wallet evidence, refuse — we have no informational edge there.
    if (market_price < 0.05 or market_price > 0.95) and not has_evidence:
        return None

    side = (cand.get("smart_money_side") or cand.get("suggested_outcome") or "yes").lower()
    # Edge sized by confluence above the 60 threshold, capped at 6%.
    raw_edge = min(0.06, max(0.005, (conf - 60) / 500.0))
    direction_signed = +raw_edge if side == "yes" else -raw_edge
    p = max(0.02, min(0.98, market_price + direction_signed))
    return {
        "p": p,
        "low": max(0.0, p - 0.08),
        "high": min(1.0, p + 0.08),
        "base_rate": market_price,
        "key_factors": [
            f"paper heuristic from confluence={conf:.0f}, side={side}",
            "wallet_evidence=" + ("yes" if has_evidence else "no"),
        ],
        "_discovery_method": "wallet_single" if has_evidence else "heuristic_paper",
    }


def _build_prompt(candidate: dict) -> str:
    q = candidate.get("market_question") or "?"
    yes_price = candidate.get("yes_price")
    end = candidate.get("hours_to_resolution")
    end_str = f"{end:.0f}h" if isinstance(end, (int, float)) and end < 24 * 30 else "30+ days"
    reasons = candidate.get("reasons", [])[:3]
    return (
        f"Market: {q}\n"
        f"Resolves in: {end_str}\n"
        f"Current YES price: {yes_price:.2f}\n"
        f"Existing signals from our system: {'; '.join(reasons) if reasons else 'none'}\n"
        f"\nEstimate the probability that this resolves YES. "
        f"Provide point estimate, 80% confidence interval (low/high), historical base rate "
        f"for analogous events, and 3-5 key factors. JSON only."
    )


def main() -> int:
    today = _today_dir()
    today.mkdir(parents=True, exist_ok=True)
    cand_path = today / "pm_candidates.json"
    if not cand_path.exists():
        print("[estimate_probability] no candidates file — skip")
        return 0
    payload = json.loads(cand_path.read_text())
    candidates = payload.get("candidates", [])
    threshold = payload.get("threshold", 60)

    passing = [c for c in candidates if c.get("confluence_score", 0) >= threshold]
    passing.sort(key=lambda x: x["confluence_score"], reverse=True)

    cache = _load_cache()
    estimates: list[dict] = []
    llm_calls = 0
    cache_hits = 0

    for cand in passing:
        mid = cand["market_id"]
        market_price = cand.get("yes_price") or 0.5

        # Insider-suspect veto BEFORE any LLM cost
        if _is_insider_suspect(cand.get("market_question", ""), cand.get("categories", [])):
            estimates.append({
                "market_id": mid,
                "market_question": cand["market_question"],
                "estimated_probability": None,
                "confluence_score": cand["confluence_score"],
                "action": "NO_BET",
                "reason": "insider-suspect category — DOJ legal risk",
            })
            continue

        # Cache hit?
        cached = cache.get(mid)
        if cached and _is_fresh(cached):
            cache_hits += 1
            est = dict(cached)
            est.update({
                "market_id": mid,
                "market_question": cand["market_question"],
                "confluence_score": cand["confluence_score"],
                "yes_price": market_price,
                "from_cache": True,
            })
            estimates.append(est)
            continue

        # Hard cap on LLM calls
        if llm_calls >= MAX_LLM_CALLS_PER_CYCLE:
            estimates.append({
                "market_id": mid,
                "market_question": cand["market_question"],
                "confluence_score": cand["confluence_score"],
                "action": "DEFER",
                "reason": f"LLM call cap ({MAX_LLM_CALLS_PER_CYCLE}) reached this cycle",
            })
            continue

        prompt = _build_prompt(cand)
        result = perplexity.ask_safe(prompt, system=SYSTEM_PROMPT, max_tokens=400, temperature=0.1)
        llm_calls += 1
        parsed = None
        if not result:
            # Paper mode: synthesize a heuristic estimate so the funnel
            # still produces paper bets when Perplexity is offline.
            parsed = _paper_heuristic_estimate(cand, market_price)
            if parsed is None:
                estimates.append({
                    "market_id": mid,
                    "market_question": cand["market_question"],
                    "confluence_score": cand["confluence_score"],
                    "action": "DEFER",
                    "reason": "Perplexity unavailable",
                })
                continue
        if parsed is None:
            parsed = _parse_answer(result.get("answer", ""))
        if not parsed or "p" not in parsed:
            estimates.append({
                "market_id": mid,
                "market_question": cand["market_question"],
                "confluence_score": cand["confluence_score"],
                "action": "DEFER",
                "reason": "could not parse probability from LLM response",
                "raw_answer": result.get("answer", "")[:300],
            })
            continue

        try:
            p = max(0.0, min(1.0, float(parsed["p"])))
            low = max(0.0, min(1.0, float(parsed.get("low", p - 0.1))))
            high = max(0.0, min(1.0, float(parsed.get("high", p + 0.1))))
            base_rate = float(parsed.get("base_rate", p)) if parsed.get("base_rate") is not None else p
            key_factors = parsed.get("key_factors") or []
        except (TypeError, ValueError):
            estimates.append({
                "market_id": mid,
                "market_question": cand["market_question"],
                "confluence_score": cand["confluence_score"],
                "action": "DEFER",
                "reason": "non-numeric probability fields",
            })
            continue

        shrunk = _shrink_to_market(p, low, high, market_price)
        est = {
            "market_id": mid,
            "market_question": cand["market_question"],
            "estimated_probability": round(shrunk, 4),
            "raw_probability": round(p, 4),
            "confidence_low": round(low, 4),
            "confidence_high": round(high, 4),
            "base_rate": round(base_rate, 4),
            "yes_price": market_price,
            "edge": round(shrunk - market_price, 4),
            "key_factors": key_factors[:5] if isinstance(key_factors, list) else [],
            "citations": (result or {}).get("citations", [])[:5],
            "source": "perplexity" if result else "paper_heuristic",
            "confluence_score": cand["confluence_score"],
            "ts": datetime.now(timezone.utc).isoformat(),
            "ttl_hours": CACHE_TTL_HOURS,
            "from_cache": False,
        }
        estimates.append(est)
        # Persist to cache (only the parts useful next cycle)
        cache[mid] = {
            "estimated_probability": est["estimated_probability"],
            "raw_probability": est["raw_probability"],
            "confidence_low": est["confidence_low"],
            "confidence_high": est["confidence_high"],
            "base_rate": est["base_rate"],
            "key_factors": est["key_factors"],
            "citations": est["citations"],
            "ts": est["ts"],
            "ttl_hours": CACHE_TTL_HOURS,
        }

    _save_cache(cache)

    out_path = today / "pm_estimates.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm_calls": llm_calls,
        "cache_hits": cache_hits,
        "estimate_count": len(estimates),
        "estimates": estimates,
    }, indent=2))
    print(
        f"[estimate_probability] estimates={len(estimates)} llm_calls={llm_calls} "
        f"cache_hits={cache_hits} → {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
