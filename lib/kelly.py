"""Kelly criterion implementation for optimal bet/position sizing.

Uses quarter-Kelly (0.25x) by default for safety. Full Kelly assumes perfect
probability estimates, which we never have. Quarter-Kelly gives ~75% of the
growth rate with dramatically less volatility and drawdown risk.
"""

import json
import os


def load_kelly_config() -> dict:
    """Load Kelly parameters from risk config."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "risk_params.json")
    with open(config_path) as f:
        config = json.load(f)
    return config


def kelly_fraction(win_prob: float, win_loss_ratio: float, fraction: float = 0.25) -> float:
    """Calculate fractional Kelly criterion bet size.

    Args:
        win_prob: Estimated probability of winning (0-1)
        win_loss_ratio: Ratio of average win to average loss (e.g., 2.0 means wins are 2x losses)
        fraction: Kelly fraction to use (0.25 = quarter-Kelly, default)

    Returns:
        Fraction of bankroll to bet (0.0 to 1.0). Returns 0 if no edge.
    """
    if win_prob <= 0 or win_prob >= 1 or win_loss_ratio <= 0:
        return 0.0

    # Kelly formula: f* = (bp - q) / b
    # where b = win/loss ratio, p = win probability, q = 1-p
    b = win_loss_ratio
    p = win_prob
    q = 1 - p

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0  # No edge, don't bet

    return min(full_kelly * fraction, 1.0)


def kelly_for_polymarket(estimated_prob: float, market_odds: float, fraction: float = None) -> dict:
    """Calculate Kelly bet size for a Polymarket position.

    Args:
        estimated_prob: Our estimated true probability (0-1)
        market_odds: Current market price/probability (0-1)
        fraction: Kelly fraction override (defaults to config value)

    Returns:
        Dict with edge_pct, kelly_bet_pct, recommended action
    """
    config = load_kelly_config()
    if fraction is None:
        fraction = config["polymarket"]["kelly_fraction"]

    min_edge = config["polymarket"]["min_edge_pct"] / 100
    max_bet = config["polymarket"]["max_bet_pct_bankroll"] / 100
    # Paper-mode override: loosen min_edge so the funnel still produces bets
    # when the Perplexity-free heuristic only generates 2-4% edges. Live mode
    # keeps the strict 5% bar.
    if os.environ.get("PAPER_MODE", "").lower() == "true":
        pm_paper = (config.get("paper_mode_overrides", {}) or {}).get("polymarket", {}) or {}
        if "min_edge_pct" in pm_paper:
            min_edge = float(pm_paper["min_edge_pct"]) / 100

    edge = estimated_prob - market_odds

    if edge < min_edge:
        return {
            "edge_pct": edge * 100,
            "kelly_bet_pct": 0,
            "action": "NO_BET",
            "reason": f"Edge {edge*100:.1f}% below minimum {min_edge*100:.1f}%",
        }

    # For binary markets: win = (1/market_odds - 1), lose = 1
    if market_odds <= 0 or market_odds >= 1:
        return {"edge_pct": edge * 100, "kelly_bet_pct": 0, "action": "NO_BET", "reason": "Invalid market odds"}

    payout_ratio = (1 / market_odds) - 1  # How much you win per dollar risked
    kelly = kelly_fraction(estimated_prob, payout_ratio, fraction)
    kelly = min(kelly, max_bet)  # Cap at max bet size

    return {
        "edge_pct": round(edge * 100, 2),
        "kelly_bet_pct": round(kelly * 100, 2),
        "payout_ratio": round(payout_ratio, 2),
        "action": "BET" if kelly > 0 else "NO_BET",
        "reason": f"Edge {edge*100:.1f}%, Kelly {kelly*100:.1f}% of bankroll",
    }


def kelly_for_trade(win_rate: float, avg_win_pct: float, avg_loss_pct: float, fraction: float = 0.25) -> dict:
    """Calculate Kelly-optimal position size for a market trade.

    Args:
        win_rate: Historical or estimated win rate (0-1)
        avg_win_pct: Average winning trade return %
        avg_loss_pct: Average losing trade return % (positive number)
        fraction: Kelly fraction

    Returns:
        Dict with kelly_pct and recommendation
    """
    if avg_loss_pct <= 0:
        return {"kelly_pct": 0, "action": "NO_TRADE", "reason": "Invalid loss parameter"}

    win_loss_ratio = avg_win_pct / avg_loss_pct
    kelly = kelly_fraction(win_rate, win_loss_ratio, fraction)

    return {
        "kelly_pct": round(kelly * 100, 2),
        "win_loss_ratio": round(win_loss_ratio, 2),
        "action": "TRADE" if kelly > 0 else "NO_TRADE",
        "reason": f"Win rate {win_rate*100:.0f}%, R:R {win_loss_ratio:.1f}, Kelly {kelly*100:.1f}%",
    }
