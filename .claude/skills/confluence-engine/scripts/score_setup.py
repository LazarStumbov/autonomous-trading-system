"""Score trade setups using weighted confluence signals. Produces a 0-100 confidence score."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import MIN_CONFLUENCE_SCORE, HIGH_CONFLUENCE_SCORE, get_effective_min_score


def load_weights() -> dict:
    """Load signal weights from watchlist config."""
    config_path = os.path.join(PROJECT_ROOT, "config", "watchlist.json")
    with open(config_path) as f:
        config = json.load(f)
    return config.get("confluence", {}).get("weights", {})


def score_confluence(confluence: dict, weights: dict = None) -> dict:
    """Score a single confluence group.

    Scoring formula:
        base_score = 40 + (unique_signal_types * 10)
        weighted_score = sum(weight * strength for each signal)
        final_score = clamp((base_score + weighted_score) / 2, 0, 100)

    Args:
        confluence: Dict from confluence_detector with signals grouped
        weights: Signal type weights (default from config)

    Returns:
        Dict with score, tier, and breakdown.
    """
    if weights is None:
        weights = load_weights()

    unique_types = confluence["unique_signal_types"]
    signals = confluence["signals"]

    # Base score from number of independent signal types.
    # Diversity multiplier rewards setups corroborated by orthogonal sources:
    # 1 type → 50, 2 → 65, 3 → 78, 4 → 88, 5+ → 95. Was a flat +10 per type;
    # the new curve makes the gap between 1-type (TA only) and 3+ (TA + news
    # + trader + volume) decisive, which is the diagnostic that distinguishes
    # genuine confluence from a single strategy lighting up.
    diversity_bonus_curve = {1: 10, 2: 25, 3: 38, 4: 48, 5: 55}
    base_score = 40 + diversity_bonus_curve.get(min(5, unique_types), 55)

    # Weighted score from individual signals
    weighted_sum = 0
    signal_breakdown = []

    for sig in signals:
        sig_type = sig["type"]
        # Handle enum values
        type_key = sig_type.value if hasattr(sig_type, "value") else str(sig_type)
        weight = weights.get(type_key, 1.0)
        strength = sig.get("strength", 0.5)
        contribution = weight * strength * 10  # Scale to meaningful range

        weighted_sum += contribution
        signal_breakdown.append({
            "type": type_key,
            "weight": weight,
            "strength": round(strength, 2),
            "contribution": round(contribution, 2),
            "source": sig.get("source", ""),
            "timeframe": sig.get("timeframe", ""),
        })

    # Combine base and weighted
    final_score = min(100, max(0, (base_score + weighted_sum) / 2))

    # Determine tier against the threshold actually in use (paper-mode aware),
    # so NO_TRADE consistently means "will not execute" across journal + gate.
    effective_min = get_effective_min_score()
    if final_score >= HIGH_CONFLUENCE_SCORE:
        tier = "HIGH_CONVICTION"
    elif final_score >= effective_min:
        tier = "STANDARD"
    else:
        tier = "NO_TRADE"

    return {
        "symbol": confluence["symbol"],
        "direction": confluence["direction"],
        "score": round(final_score, 1),
        "tier": tier,
        "base_score": base_score,
        "weighted_sum": round(weighted_sum, 2),
        "unique_signal_types": unique_types,
        "total_signals": len(signals),
        "breakdown": signal_breakdown,
        "actionable": final_score >= effective_min,
    }


def score_all_confluences(confluences_path: str = None) -> list[dict]:
    """Score all confluences from file.

    Returns:
        List of scored setups, sorted by score (highest first).
    """
    if confluences_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        confluences_path = os.path.join(PROJECT_ROOT, "data", "signals", today, "confluences.json")

    with open(confluences_path) as f:
        data = json.load(f)

    confluences = data.get("confluences", [])
    weights = load_weights()

    scored = [score_confluence(c, weights) for c in confluences]
    scored.sort(key=lambda s: s["score"], reverse=True)

    return scored


def save_scored(scored: list[dict], output_dir: str = None) -> str:
    """Save scored setups."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    filepath = os.path.join(output_dir, "scored_setups.json")

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scored_setups": scored,
            "actionable_count": sum(1 for s in scored if s["actionable"]),
            "total": len(scored),
        }, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Score confluence setups")
    parser.add_argument("--input", help="Path to confluences.json")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    scored = score_all_confluences(args.input)

    if not args.no_save:
        path = save_scored(scored)
        print(f"Saved to: {path}")

    actionable = [s for s in scored if s["actionable"]]
    print(f"\n{len(actionable)}/{len(scored)} actionable setups (score >= {MIN_CONFLUENCE_SCORE}):")
    for s in scored:
        marker = ">>>" if s["actionable"] else "   "
        print(f"  {marker} [{s['score']:.0f}] {s['symbol']} {s['direction'].upper()} "
              f"({s['tier']}) — {s['unique_signal_types']} types, {s['total_signals']} signals")


if __name__ == "__main__":
    main()
