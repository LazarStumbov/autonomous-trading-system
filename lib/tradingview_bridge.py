"""Thin wrapper around the TradingView MCP for our scripts.

The MCP exposes 78 tools; this bridge selects the high-leverage subset for
day-trading workflows: chart snapshots, multi-TF alignment, batch scans,
screenshot-on-execute, and Pine indicator output reading.

Implementation note:
    The bridge expects an MCP client capable of calling
    `mcp__tradingview__<tool>` functions. Inside Claude Code, those tools are
    invoked directly by the agent. From a non-Claude script (e.g. a Modal
    cron) you'd typically call the MCP via stdio; for those callers we
    expose the helpers as functions that accept a `mcp_call(tool, **kwargs)`
    callable, so wiring is up to the caller.

This module never imports MCP libraries directly — it stays
import-cheap so the screener can include it without paying a startup cost on
every cron tick.
"""

from __future__ import annotations
from typing import Any, Callable, Optional


MCPCall = Callable[..., dict]


def snapshot_chart(mcp_call: MCPCall, symbol: str, timeframe: str = "1h") -> dict:
    """Snapshot a single symbol's chart state + study values.

    Returns a dict with keys: price (last, OHLC), studies (per-indicator),
    timeframe, and a captured_at timestamp.

    Pass-through wrapper around `chart_set_symbol` + `chart_set_timeframe` +
    `chart_get_state` + `data_get_study_values`. Does NOT capture a
    screenshot — call `screenshot_setup()` separately for that.
    """
    mcp_call("chart_set_symbol", symbol=symbol)
    mcp_call("chart_set_timeframe", timeframe=timeframe)
    state = mcp_call("chart_get_state") or {}
    quote = mcp_call("quote_get") or {}
    studies = mcp_call("data_get_study_values") or {}
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": {
            "last": quote.get("last"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            "volume": quote.get("volume"),
        },
        "studies": studies,
        "indicators_loaded": (state.get("indicators") or []),
    }


def multi_tf_alignment(
    mcp_call: MCPCall,
    symbol: str,
    timeframes: Optional[list[str]] = None,
) -> dict:
    """Pull study values across multiple timeframes for confluence checks.

    Default TFs: 15m / 1h / 4h / 1d — matching watchlist.json.

    Returns a dict keyed by timeframe with `trend`, `momentum`, `volatility`
    classifications derived from the visible studies (EMA stack, RSI, ATR, BB
    width). The screener uses this to gate cross-TF signals.
    """
    timeframes = timeframes or ["15m", "1h", "4h", "1d"]
    out: dict[str, dict] = {}
    mcp_call("chart_set_symbol", symbol=symbol)
    for tf in timeframes:
        mcp_call("chart_set_timeframe", timeframe=tf)
        studies = mcp_call("data_get_study_values") or {}
        out[tf] = _classify_tf(studies)
    return {"symbol": symbol, "timeframes": out}


def _classify_tf(studies: dict) -> dict:
    """Reduce raw study values into trend / momentum / volatility flags.

    Heuristics (match the playbook):
      - trend: EMA-20 > EMA-50 > EMA-200 = bull; reverse = bear; else mixed.
      - momentum: RSI > 60 bull, < 40 bear, else neutral.
      - volatility: BB width relative to median width = expanding / contracting / normal.
    """
    s = studies or {}
    e20 = _safe_num(s.get("EMA 20") or s.get("EMA20") or s.get("ema20"))
    e50 = _safe_num(s.get("EMA 50") or s.get("EMA50") or s.get("ema50"))
    e200 = _safe_num(s.get("EMA 200") or s.get("EMA200") or s.get("ema200"))
    rsi = _safe_num(s.get("RSI") or s.get("rsi") or s.get("RSI 14"))
    atr = _safe_num(s.get("ATR") or s.get("atr"))

    trend = "mixed"
    if all(v is not None for v in (e20, e50, e200)):
        if e20 > e50 > e200:
            trend = "bull"
        elif e20 < e50 < e200:
            trend = "bear"

    momentum = "neutral"
    if rsi is not None:
        if rsi > 60:
            momentum = "bull"
        elif rsi < 40:
            momentum = "bear"

    return {
        "trend": trend,
        "momentum": momentum,
        "rsi": rsi,
        "atr": atr,
        "ema20": e20,
        "ema50": e50,
        "ema200": e200,
    }


def _safe_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def screenshot_setup(mcp_call: MCPCall, symbol: str, save_path: str, region: str = "chart") -> str:
    """Capture a chart screenshot. Returns saved path on success.

    Called from `execution_engine.py` immediately after a fill so the trade
    journal has visual evidence — the path is written into trades.reasoning
    as `chart_url`.
    """
    mcp_call("chart_set_symbol", symbol=symbol)
    res = mcp_call("capture_screenshot", region=region, save_path=save_path) or {}
    return res.get("path", save_path)


def batch_scan(mcp_call: MCPCall, symbols: list[str], study_filter: Optional[str] = None) -> list[dict]:
    """Sweep a watchlist and pull study values per symbol in one call.

    Wraps `batch_run` — the MCP runs the action across all symbols server-
    side, much cheaper than N round-trips. Returns a list of dicts:
    [{symbol, studies, ...}, ...]
    """
    res = mcp_call(
        "batch_run",
        symbols=symbols,
        action="data_get_study_values",
        study_filter=study_filter,
    ) or {}
    return res.get("results", [])


def read_pine_levels(mcp_call: MCPCall, study_filter: str) -> dict:
    """Read levels/labels/zones from a custom Pine indicator on the chart.

    `study_filter` targets a specific indicator by name (e.g. "ConfluenceOverlay").
    Returns a dict with `lines`, `labels`, `tables`, `boxes` lists.
    """
    return {
        "lines": (mcp_call("data_get_pine_lines", study_filter=study_filter) or {}).get("lines", []),
        "labels": (mcp_call("data_get_pine_labels", study_filter=study_filter) or {}).get("labels", []),
        "tables": (mcp_call("data_get_pine_tables", study_filter=study_filter) or {}).get("tables", []),
        "boxes": (mcp_call("data_get_pine_boxes", study_filter=study_filter) or {}).get("boxes", []),
    }
