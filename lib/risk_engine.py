"""Core risk calculation engine. The guardrail that prevents catastrophic losses.

Every trade MUST pass through check_trade() before execution.
The risk engine has absolute veto power.
"""

from __future__ import annotations

import json
import os
from lib.db import get_connection, get_open_trades, get_system_state, get_daily_stats
from lib.constants import RiskVerdict, MAX_RISK_PER_TRADE_PCT, MAX_DAILY_DRAWDOWN_PCT


def load_risk_config() -> dict:
    """Load risk parameters from config file.

    When PAPER_MODE=true, the `paper_mode_overrides` section is merged into the
    relevant fields. This keeps live trading strict while letting paper mode
    generate a richer trade sample for review.
    """
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "risk_params.json")
    with open(config_path) as f:
        config = json.load(f)

    if os.environ.get("PAPER_MODE", "").lower() == "true":
        ov = config.get("paper_mode_overrides", {})
        if "min_risk_reward_ratio" in ov:
            config["market_trading"]["min_risk_reward_ratio"] = ov["min_risk_reward_ratio"]
        if "max_portfolio_exposure_pct" in ov:
            config["market_trading"]["max_portfolio_exposure_pct"] = ov["max_portfolio_exposure_pct"]
        if "max_daily_drawdown_pct" in ov:
            config["market_trading"]["circuit_breakers"]["daily_loss_halt_pct"] = ov["max_daily_drawdown_pct"]
        if "initial_market_usd" in ov:
            config["capital"]["initial_market_usd"] = ov["initial_market_usd"]

    return config


_LEVERAGE_PER_ASSET_CACHE = None


def load_leverage_per_asset() -> dict:
    """Load per-asset leverage tiers. Cached for the process lifetime since
    it's read on every trade build."""
    global _LEVERAGE_PER_ASSET_CACHE
    if _LEVERAGE_PER_ASSET_CACHE is not None:
        return _LEVERAGE_PER_ASSET_CACHE
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "leverage_per_asset.json")
    try:
        with open(path) as f:
            _LEVERAGE_PER_ASSET_CACHE = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _LEVERAGE_PER_ASSET_CACHE = {}
    return _LEVERAGE_PER_ASSET_CACHE


def lookup_asset_leverage_cap(asset_symbol: str, confluence_score: float) -> int | None:
    """Return the per-asset leverage cap based on confluence score, or None
    if the symbol isn't listed (caller falls back to global limits)."""
    cfg = load_leverage_per_asset()
    if not cfg or not asset_symbol:
        return None
    sym = asset_symbol.upper()
    for class_name, class_cfg in cfg.items():
        if class_name.startswith("_"):
            continue
        if not class_cfg.get("enabled"):
            continue
        for tier_name, tier in (class_cfg.get("tiers") or {}).items():
            symbols = [s.upper() for s in tier.get("symbols", [])]
            if sym in symbols:
                if confluence_score >= 80:
                    return int(tier.get("high_conviction_80", tier.get("default", 3)))
                if confluence_score >= 70:
                    return int(tier.get("high_conviction_70", tier.get("default", 3)))
                return int(tier.get("default", 3))
    return None


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


def check_leverage(
    requested_leverage: float,
    confluence_score: float = 0,
    asset_symbol: str | None = None,
) -> dict:
    """Validate leverage against limits.

    The cap is resolved in this order:
      1. Per-asset tier from `config/leverage_per_asset.json` (if the symbol
         is listed under an enabled class).
      2. Global tier from `config/risk_params.json` (`default` /
         `high_conviction_max` based on confluence).
    The `absolute_max` global ceiling is always enforced as an upper bound.

    Returns:
        Dict with approved_leverage, verdict, reason, source.
    """
    config = load_risk_config()
    limits = config["market_trading"]["leverage_limits"]

    per_asset_cap = lookup_asset_leverage_cap(asset_symbol or "", confluence_score)

    if per_asset_cap is not None:
        max_allowed = per_asset_cap
        source = f"per_asset[{asset_symbol}]"
    else:
        if confluence_score >= limits["high_conviction_min_confluence"]:
            max_allowed = limits["high_conviction_max"]
        else:
            max_allowed = limits["default"]
        source = "global"

    approved = min(requested_leverage, max_allowed, limits["absolute_max"])

    return {
        "requested": requested_leverage,
        "approved": approved,
        "max_allowed": max_allowed,
        "source": source,
        "verdict": RiskVerdict.PASS if requested_leverage <= max_allowed else RiskVerdict.FAIL,
        "reason": f"Leverage {approved}x approved (max {max_allowed}x via {source} for confluence {confluence_score})",
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

    # 5. Leverage (per-asset cap when symbol matches config/leverage_per_asset.json)
    checks["leverage"] = check_leverage(requested_leverage, confluence_score, asset_symbol=asset)
    if checks["leverage"]["verdict"] == RiskVerdict.FAIL:
        failures.append(checks["leverage"]["reason"])

    # 6. Portfolio exposure (use margin required, not notional)
    notional = checks["position_size"]["position_size"] * entry_price
    margin_required = notional  # margin = notional / leverage, but exposure tracks notional risk
    checks["exposure"] = check_portfolio_exposure(capital, margin_required, db_path)
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
