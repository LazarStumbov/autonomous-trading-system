"""Core risk calculation engine. The guardrail that prevents catastrophic losses.

Every trade MUST pass through check_trade() before execution.
The risk engine has absolute veto power.
"""

import json
import os
from lib.db import get_connection, get_open_trades, get_system_state, get_daily_stats
from lib.constants import RiskVerdict, MAX_RISK_PER_TRADE_PCT, MAX_DAILY_DRAWDOWN_PCT


def load_risk_config() -> dict:
    """Load risk parameters from config file."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "risk_params.json")
    with open(config_path) as f:
        return json.load(f)


def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss_price: float,
    max_risk_pct: float = None,
) -> dict:
    """Calculate position size based on risk parameters.

    Args:
        capital: Current account capital
        entry_price: Planned entry price
        stop_loss_price: Planned stop loss price
        max_risk_pct: Max % of capital to risk (default from config)

    Returns:
        Dict with position_size, risk_usd, risk_pct
    """
    config = load_risk_config()
    if max_risk_pct is None:
        max_risk_pct = config["market_trading"]["max_risk_per_trade_pct"]

    risk_per_unit = abs(entry_price - stop_loss_price)
    if risk_per_unit == 0:
        return {"position_size": 0, "error": "Stop loss cannot equal entry price"}

    max_risk_usd = capital * (max_risk_pct / 100)
    position_size = max_risk_usd / risk_per_unit

    return {
        "position_size": round(position_size, 6),
        "position_value_usd": round(position_size * entry_price, 2),
        "risk_usd": round(max_risk_usd, 2),
        "risk_pct": max_risk_pct,
        "risk_per_unit": round(risk_per_unit, 6),
    }


def check_leverage(requested_leverage: float, confluence_score: float = 0) -> dict:
    """Validate leverage against limits.

    Returns:
        Dict with approved_leverage, verdict, reason
    """
    config = load_risk_config()
    limits = config["market_trading"]["leverage_limits"]

    max_allowed = limits["default"]
    if confluence_score >= limits["high_conviction_min_confluence"]:
        max_allowed = limits["high_conviction_max"]

    approved = min(requested_leverage, max_allowed, limits["absolute_max"])

    return {
        "requested": requested_leverage,
        "approved": approved,
        "max_allowed": max_allowed,
        "verdict": RiskVerdict.PASS if requested_leverage <= max_allowed else RiskVerdict.FAIL,
        "reason": f"Leverage {approved}x approved (max {max_allowed}x for confluence {confluence_score})",
    }


def check_portfolio_exposure(capital: float, new_position_value: float, db_path: str = None) -> dict:
    """Check if adding a new position would exceed portfolio exposure limits.

    Returns:
        Dict with current_exposure_pct, new_exposure_pct, verdict
    """
    config = load_risk_config()
    max_exposure = config["market_trading"]["max_portfolio_exposure_pct"]

    conn = get_connection(db_path) if db_path else get_connection()
    open_trades = get_open_trades(conn)
    conn.close()

    current_exposure = sum(
        t.get("quantity", 0) * t.get("entry_price", 0) for t in open_trades
    )
    new_total = current_exposure + new_position_value
    exposure_pct = (new_total / capital) * 100 if capital > 0 else 100

    return {
        "current_exposure_usd": round(current_exposure, 2),
        "new_position_usd": round(new_position_value, 2),
        "total_exposure_usd": round(new_total, 2),
        "exposure_pct": round(exposure_pct, 2),
        "max_allowed_pct": max_exposure,
        "verdict": RiskVerdict.PASS if exposure_pct <= max_exposure else RiskVerdict.FAIL,
        "reason": f"Exposure {exposure_pct:.1f}% vs limit {max_exposure}%",
    }


def check_correlated_positions(asset: str, direction: str, db_path: str = None) -> dict:
    """Check if adding this position would create too many correlated positions.

    Returns:
        Dict with correlated_count, verdict
    """
    config = load_risk_config()
    max_correlated = config["market_trading"]["max_correlated_positions"]

    conn = get_connection(db_path) if db_path else get_connection()
    open_trades = get_open_trades(conn)
    conn.close()

    same_direction = [t for t in open_trades if t.get("direction") == direction]

    return {
        "same_direction_count": len(same_direction),
        "max_allowed": max_correlated,
        "verdict": RiskVerdict.PASS if len(same_direction) < max_correlated else RiskVerdict.FAIL,
        "reason": f"{len(same_direction)} positions in {direction} direction (max {max_correlated})",
    }


def check_drawdown(capital: float, db_path: str = None) -> dict:
    """Check current drawdown against daily and weekly limits.

    Returns:
        Dict with daily_drawdown_pct, weekly_drawdown_pct, verdict
    """
    config = load_risk_config()
    daily_limit = config["market_trading"]["circuit_breakers"]["daily_loss_halt_pct"]
    weekly_limit = config["market_trading"]["circuit_breakers"]["weekly_loss_halt_pct"]

    conn = get_connection(db_path) if db_path else get_connection()
    daily_pnl = float(get_system_state(conn, "daily_pnl_usd") or "0")
    weekly_pnl = float(get_system_state(conn, "weekly_pnl_usd") or "0")
    conn.close()

    daily_dd_pct = abs(min(daily_pnl, 0)) / capital * 100 if capital > 0 else 0
    weekly_dd_pct = abs(min(weekly_pnl, 0)) / capital * 100 if capital > 0 else 0

    daily_ok = daily_dd_pct < daily_limit
    weekly_ok = weekly_dd_pct < weekly_limit

    verdict = RiskVerdict.PASS if (daily_ok and weekly_ok) else RiskVerdict.FAIL
    reasons = []
    if not daily_ok:
        reasons.append(f"Daily drawdown {daily_dd_pct:.1f}% exceeds {daily_limit}% limit")
    if not weekly_ok:
        reasons.append(f"Weekly drawdown {weekly_dd_pct:.1f}% exceeds {weekly_limit}% limit")

    return {
        "daily_pnl_usd": daily_pnl,
        "weekly_pnl_usd": weekly_pnl,
        "daily_drawdown_pct": round(daily_dd_pct, 2),
        "weekly_drawdown_pct": round(weekly_dd_pct, 2),
        "verdict": verdict,
        "reason": "; ".join(reasons) if reasons else "Drawdown within limits",
    }


def check_circuit_breakers(db_path: str = None) -> dict:
    """Check if any circuit breakers are triggered.

    Returns:
        Dict with halted, reason
    """
    config = load_risk_config()
    breakers = config["market_trading"]["circuit_breakers"]

    conn = get_connection(db_path) if db_path else get_connection()
    halted = get_system_state(conn, "trading_halted") == "true"
    consecutive_losses = int(get_system_state(conn, "consecutive_losses") or "0")
    conn.close()

    if halted:
        return {"halted": True, "verdict": RiskVerdict.FAIL, "reason": "Trading manually halted"}

    if consecutive_losses >= breakers["halt_after_consecutive_losses"]:
        return {
            "halted": True,
            "verdict": RiskVerdict.FAIL,
            "reason": f"{consecutive_losses} consecutive losses (limit: {breakers['halt_after_consecutive_losses']}). "
                      f"Halted for {breakers['halt_duration_hours']}h.",
        }

    return {"halted": False, "verdict": RiskVerdict.PASS, "reason": "No circuit breakers active"}


def check_trade(
    capital: float,
    asset: str,
    direction: str,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    requested_leverage: float,
    confluence_score: float = 0,
    db_path: str = None,
) -> dict:
    """Full pre-trade risk validation. MUST PASS before any execution.

    This is the single entry point for risk checking. It runs ALL checks
    and returns a consolidated verdict.

    Returns:
        Dict with overall verdict, position sizing, and all individual check results
    """
    config = load_risk_config()
    min_rr = config["market_trading"]["min_risk_reward_ratio"]

    checks = {}
    failures = []

    # 1. Circuit breakers
    checks["circuit_breakers"] = check_circuit_breakers(db_path)
    if checks["circuit_breakers"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["circuit_breakers"]["reason"])

    # 2. Drawdown limits
    checks["drawdown"] = check_drawdown(capital, db_path)
    if checks["drawdown"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["drawdown"]["reason"])

    # 3. Risk-reward ratio
    risk_distance = abs(entry_price - stop_loss_price)
    reward_distance = abs(take_profit_price - entry_price)
    rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0
    rr_ok = rr_ratio >= min_rr
    checks["risk_reward"] = {
        "ratio": round(rr_ratio, 2),
        "min_required": min_rr,
        "verdict": RiskVerdict.PASS if rr_ok else RiskVerdict.FAIL,
        "reason": f"R:R {rr_ratio:.1f} vs minimum {min_rr}",
    }
    if not rr_ok:
        failures.append(checks["risk_reward"]["reason"])

    # 4. Position sizing
    checks["position_size"] = calculate_position_size(capital, entry_price, stop_loss_price)

    # 5. Leverage
    checks["leverage"] = check_leverage(requested_leverage, confluence_score)
    if checks["leverage"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["leverage"]["reason"])

    # 6. Portfolio exposure
    position_value = checks["position_size"]["position_size"] * entry_price * checks["leverage"]["approved"]
    checks["exposure"] = check_portfolio_exposure(capital, position_value, db_path)
    if checks["exposure"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["exposure"]["reason"])

    # 7. Correlated positions
    checks["correlation"] = check_correlated_positions(asset, direction, db_path)
    if checks["correlation"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["correlation"]["reason"])

    # 8. Stop loss present
    has_sl = stop_loss_price is not None and stop_loss_price > 0
    checks["stop_loss"] = {
        "present": has_sl,
        "verdict": RiskVerdict.PASS if has_sl else RiskVerdict.FAIL,
        "reason": "Stop loss set" if has_sl else "STOP LOSS REQUIRED",
    }
    if not has_sl:
        failures.append("No stop loss set")

    # Consolidated verdict
    overall = RiskVerdict.PASS if len(failures) == 0 else RiskVerdict.FAIL

    return {
        "verdict": overall,
        "failures": failures,
        "failure_count": len(failures),
        "checks": checks,
        "recommended_position": {
            "size": checks["position_size"]["position_size"],
            "leverage": checks["leverage"]["approved"],
            "stop_loss": stop_loss_price,
            "take_profit": take_profit_price,
            "risk_usd": checks["position_size"]["risk_usd"],
        },
    }
