"""Localhost trading dashboard — read-only.

Run:
    python3 dashboard/app.py
    open http://127.0.0.1:8765

Bound to 127.0.0.1 only. No auth (mitigation: never expose). All routes are
read-only against data/db/trading.db. Write attempts return 405.

Dependencies: fastapi, uvicorn, jinja2, markdown. (`pip install fastapi
uvicorn jinja2 markdown` if missing.) Chart.js is loaded from a CDN; if the
CDN is unreachable, charts degrade to plain numbers.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import AsyncGenerator

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, Request  # type: ignore
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore
from fastapi.templating import Jinja2Templates  # type: ignore

from lib.db import get_connection

try:
    import markdown as md  # type: ignore
except ImportError:
    md = None  # type: ignore

DASH_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(DASH_DIR / "templates"))

app = FastAPI(title="Trading Bot Dashboard", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(DASH_DIR / "static")), name="static")

# ---------- poll cache ----------

_poll_cache: dict = {"ts": 0, "data": None}
_POLL_TTL = 10  # seconds


# ---------- helpers ----------

def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _qone(sql: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------- middleware: block writes ----------

@app.middleware("http")
async def block_writes(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        # Allow only specific write endpoints from localhost
        allowed_writes = {"/api/halt", "/api/resume"}
        if request.url.path not in allowed_writes:
            return JSONResponse({"error": "dashboard is read-only"}, status_code=405)
    return await call_next(request)


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    halted = _qone("SELECT value FROM system_state WHERE key='trading_halted'") or {}
    open_positions = _q("SELECT * FROM trades WHERE status='open' ORDER BY opened_at DESC")
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = _qone(
        "SELECT SUM(pnl_usd) AS pnl, COUNT(*) AS n FROM trades WHERE date(closed_at)=?",
        (today_iso,),
    ) or {}
    week_cut = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    weekly = _qone(
        "SELECT SUM(pnl_usd) AS pnl, COUNT(*) AS n FROM trades WHERE closed_at>=?",
        (week_cut,),
    ) or {}
    api_cost = _qone(
        "SELECT COALESCE(SUM(usd_cost), 0) AS mtd FROM api_costs WHERE timestamp LIKE ?",
        (datetime.now(timezone.utc).strftime("%Y-%m") + "%",),
    ) or {"mtd": 0}
    paper_balance = _qone("SELECT value FROM system_state WHERE key='paper_balance_usd'")
    consecutive = _qone("SELECT value FROM system_state WHERE key='consecutive_losses'")
    return TEMPLATES.TemplateResponse(
        "index.html",
        {
            "request": request,
            "halted": (halted.get("value") == "true"),
            "open_positions": open_positions,
            "daily_pnl": daily.get("pnl") or 0,
            "daily_count": daily.get("n") or 0,
            "weekly_pnl": weekly.get("pnl") or 0,
            "weekly_count": weekly.get("n") or 0,
            "api_mtd": api_cost.get("mtd") or 0,
            "paper_balance_usd": float((paper_balance or {}).get("value", 0) or 0),
            "consecutive_losses": int((consecutive or {}).get("value", "0") or 0),
        },
    )


@app.get("/trades", response_class=HTMLResponse)
def trades(request: Request, status: str = "", strategy: str = ""):
    sql = "SELECT * FROM trades WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if strategy:
        sql += " AND strategy=?"
        params.append(strategy)
    sql += " ORDER BY opened_at DESC LIMIT 200"
    rows = _q(sql, tuple(params))
    return TEMPLATES.TemplateResponse(
        "trades.html",
        {"request": request, "trades": rows, "status": status, "strategy": strategy},
    )


@app.get("/trades/{trade_id}", response_class=HTMLResponse)
def trade_detail(request: Request, trade_id: int):
    t = _qone("SELECT * FROM trades WHERE id=?", (trade_id,))
    if not t:
        raise HTTPException(404)
    reasoning_raw = t.get("reasoning") or ""
    reasoning_parsed = None
    try:
        reasoning_parsed = json.loads(reasoning_raw) if reasoning_raw.strip().startswith("{") else None
        if reasoning_parsed:
            reasoning_pretty = json.dumps(reasoning_parsed, indent=2, default=str)
        else:
            reasoning_pretty = reasoning_raw
    except Exception:
        reasoning_pretty = reasoning_raw

    partial_closes: list = []
    try:
        partial_closes = _q(
            "SELECT * FROM partial_closes WHERE trade_id=? ORDER BY closed_at ASC",
            (trade_id,),
        )
    except Exception:
        pass

    return TEMPLATES.TemplateResponse(
        "trade_detail.html",
        {
            "request": request,
            "trade": t,
            "reasoning_pretty": reasoning_pretty,
            "reasoning_parsed": reasoning_parsed,
            "partial_closes": partial_closes,
        },
    )


@app.get("/strategies", response_class=HTMLResponse)
def strategies(request: Request):
    rows = _q(
        """SELECT r.id, r.mode, r.source, r.demotion_reason,
                  p.total_trades, p.win_rate, p.profit_factor,
                  p.sharpe_30d, p.last_trade_at, p.total_pnl_usd
           FROM strategy_registry r
           LEFT JOIN strategy_performance p ON p.strategy_id = r.id
           ORDER BY p.profit_factor DESC NULLS LAST, r.id ASC"""
    )
    # Group by mode for the ladder view
    from collections import defaultdict
    by_mode: dict = defaultdict(list)
    for r in rows:
        by_mode[r.get("mode") or "unknown"].append(r)

    # Promotion candidates: paper with >= 20 trades, PF > 1.4, sharpe > 1.0
    promotable = [
        r for r in by_mode.get("paper", [])
        if (r.get("total_trades") or 0) >= 20
        and (r.get("profit_factor") or 0) > 1.4
        and (r.get("sharpe_30d") or 0) > 1.0
    ]

    return TEMPLATES.TemplateResponse(
        "strategies.html",
        {
            "request": request,
            "strategies": rows,
            "by_mode": dict(by_mode),
            "promotable": promotable,
            "mode_order": ["live", "paper", "backtest", "disabled", "unknown"],
        },
    )


@app.get("/backtests", response_class=HTMLResponse)
def backtests(request: Request, strategy_id: str = ""):
    sql = "SELECT * FROM backtest_results"
    params: list = []
    if strategy_id:
        sql += " WHERE strategy_id=?"
        params.append(strategy_id)
    sql += " ORDER BY run_at DESC LIMIT 200"
    rows = _q(sql, tuple(params))
    return TEMPLATES.TemplateResponse(
        "backtests.html", {"request": request, "rows": rows, "strategy_id": strategy_id}
    )


@app.get("/equity", response_class=HTMLResponse)
def equity(request: Request):
    rows = _q("SELECT date, realized_pnl AS total_pnl, ending_capital AS cumulative_pnl FROM daily_pnl ORDER BY date ASC")
    return TEMPLATES.TemplateResponse("equity.html", {"request": request, "rows": rows})


@app.get("/memory", response_class=HTMLResponse)
def memory(request: Request, file: str = "DAILY-BRIEF.md"):
    safe = Path(file).name  # block traversal
    p = Path(PROJECT_ROOT) / "memory" / safe
    if not p.exists():
        raise HTTPException(404, f"no memory file {safe}")
    text = p.read_text()
    html = md.markdown(text) if md is not None else f"<pre>{text}</pre>"
    files = sorted(f.name for f in (Path(PROJECT_ROOT) / "memory").glob("*.md"))
    return TEMPLATES.TemplateResponse(
        "memory.html", {"request": request, "files": files, "current": safe, "html": html}
    )


@app.get("/reviews", response_class=HTMLResponse)
def reviews(request: Request):
    base = Path(PROJECT_ROOT) / "reviews"
    out = {"pending": [], "completed": [], "archive": []}
    for bucket in out.keys():
        d = base / bucket
        if d.exists():
            out[bucket] = sorted(p.name for p in d.glob("**/*.md"))
    return TEMPLATES.TemplateResponse("reviews.html", {"request": request, **out})


@app.get("/api-costs", response_class=HTMLResponse)
def api_costs(request: Request):
    try:
        from lib.anthropic_cost_tracker import cost_summary  # type: ignore
        cs = cost_summary()
    except Exception as e:
        cs = {"error": str(e), "mtd_usd": 0, "by_model": []}
    return TEMPLATES.TemplateResponse("api_costs.html", {"request": request, "cs": cs})


# JSON API for charts ------------------------------------------------------

@app.get("/api/equity.json", response_class=JSONResponse)
def equity_json():
    rows = _q("SELECT date, realized_pnl AS total_pnl, ending_capital AS cumulative_pnl FROM daily_pnl ORDER BY date ASC")
    return rows


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


# Single-pane operational view (P7 of stabilization plan) ------------------

@app.get("/health", response_class=JSONResponse)
def health():
    """Operational snapshot: cron heartbeats, open positions, risk, MTD costs.

    The point of this route is: a fresh observer can read it in one HTTP call
    and tell whether the system is alive, what it's doing, and where the
    money is. No HTML, no Chart.js — just JSON for grep/jq/curl.
    """
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)

    # 1. Cron heartbeats per job
    heartbeats = _q(
        "SELECT key, value FROM system_state WHERE key LIKE 'last_cron_at_%'"
    )
    cron_status: dict[str, dict] = {}
    for r in heartbeats:
        job = r["key"].replace("last_cron_at_", "")
        try:
            ts = _dt.fromisoformat(r["value"].replace("Z", "+00:00"))
            age_min = (now - ts).total_seconds() / 60
            cron_status[job] = {
                "last_at": r["value"],
                "age_minutes": round(age_min, 1),
                "stale": age_min > 120,  # >2h = problem
            }
        except (ValueError, AttributeError):
            cron_status[job] = {"last_at": r["value"], "age_minutes": None, "stale": True}

    # 2. Open positions + book health
    open_positions = _q(
        """SELECT id, pillar, asset, direction, entry_price, quantity, leverage,
                  COALESCE(broker,'?') AS broker, opened_at
             FROM trades WHERE status='open' ORDER BY pillar, id"""
    )
    gross = sum(
        float(p["entry_price"] or 0) * float(p["quantity"] or 0) * float(p["leverage"] or 1)
        for p in open_positions if p["pillar"] == "market"
    )

    # 3. Latest portfolio risk snapshot
    risk = _qone("SELECT * FROM portfolio_risk_snapshots ORDER BY id DESC LIMIT 1")

    # 4. MTD P&L from daily_pnl + paper balance
    month_prefix = now.strftime("%Y-%m")
    mtd = _qone(
        "SELECT COALESCE(SUM(realized_pnl),0) AS mtd_pnl, MAX(ending_capital) AS last_capital "
        "FROM daily_pnl WHERE date LIKE ?",
        (f"{month_prefix}%",),
    )
    paper_balance = _qone("SELECT value FROM system_state WHERE key='paper_balance_usd'")

    # 5. MTD API spend + cap
    api_total = _qone(
        "SELECT COALESCE(SUM(usd_cost),0) AS mtd_usd, COUNT(*) AS calls "
        "FROM api_costs WHERE timestamp LIKE ?",
        (f"{month_prefix}%",),
    )
    api_by_job = _q(
        "SELECT job, COUNT(*) AS calls, COALESCE(SUM(usd_cost),0) AS cost "
        "FROM api_costs WHERE timestamp LIKE ? GROUP BY job ORDER BY cost DESC LIMIT 5",
        (f"{month_prefix}%",),
    )

    # 6. Last 5 agent_actions (so we can verify the brain is firing)
    agent = _q(
        "SELECT timestamp, job, model, ok, ROUND(usd_cost,4) AS usd_cost "
        "FROM agent_actions ORDER BY id DESC LIMIT 5"
    )

    # 7. Strategy mode breakdown
    strat_modes = _q(
        "SELECT mode, COUNT(*) AS n FROM strategy_registry GROUP BY mode ORDER BY n DESC"
    )

    # 8. System halt + circuit breaker state
    halt = _qone("SELECT value FROM system_state WHERE key='trading_halted'")
    consecutive = _qone("SELECT value FROM system_state WHERE key='consecutive_losses'")
    broker_mode_state = _qone("SELECT value FROM system_state WHERE key='broker_mode'")

    # 9. Headline-level OK/FAIL flags
    market_scan_age = cron_status.get("market_scan", {}).get("age_minutes")
    flags = {
        "cron_alive": (market_scan_age is not None and market_scan_age < 120),
        "trading_halted": (halt and (halt["value"] or "").lower() == "true"),
        "brain_firing": len(agent) > 0,
        "book_clean": gross < 5000,  # paper allows 250% gross on $500 = ~$1250 expected
        "no_loss_streak": int((consecutive or {}).get("value", "0") or 0) < 3,
    }
    flags["overall_ok"] = (
        flags["cron_alive"]
        and not flags["trading_halted"]
        and flags["no_loss_streak"]
    )

    return {
        "generated_at": now.isoformat(),
        "flags": flags,
        "cron_status": cron_status,
        "open_positions": {
            "count": len(open_positions),
            "gross_notional_usd": round(gross, 2),
            "by_pillar": {
                p: sum(1 for x in open_positions if x["pillar"] == p)
                for p in ("market", "polymarket")
            },
            "positions": open_positions[:25],  # cap response size
        },
        "risk_snapshot": risk,
        "pnl": {
            "paper_balance_usd": float((paper_balance or {}).get("value", 0) or 0),
            "mtd_realized_pnl": (mtd or {}).get("mtd_pnl"),
        },
        "api_spend_mtd": {
            "total_usd": float((api_total or {}).get("mtd_usd", 0) or 0),
            "total_calls": int((api_total or {}).get("calls", 0) or 0),
            "by_job": api_by_job,
        },
        "agent_actions_recent": agent,
        "strategy_modes": strat_modes,
        "system_state": {
            "trading_halted": (halt or {}).get("value"),
            "consecutive_losses": (consecutive or {}).get("value"),
            "broker_mode_db_hint": (broker_mode_state or {}).get("value"),
        },
    }


@app.get("/health/summary", response_class=PlainTextResponse)
def health_summary():
    """One-screen text summary for terminal/Telegram. ~10 lines."""
    h = health()
    lines = []
    lines.append(f"as of: {h['generated_at']}")
    lines.append(f"flags: " + " ".join(f"{k}={'✓' if v else '✗'}" for k, v in h["flags"].items()))
    cs = h["cron_status"]
    for job in sorted(cs.keys()):
        x = cs[job]
        age = x.get("age_minutes")
        mark = "⚠" if x.get("stale") else "✓"
        lines.append(f"  cron {job:20s} {mark} last={age:.0f}min ago" if age is not None else f"  cron {job:20s} {mark} last=?")
    op = h["open_positions"]
    lines.append(f"open: {op['count']} positions, gross ${op['gross_notional_usd']:,.0f}")
    if h.get("risk_snapshot"):
        r = h["risk_snapshot"]
        lines.append(f"risk: VaR1d95=${r['var_95_1d_usd']:.2f} ({r['var_95_pct']:.1f}%) "
                     f"maxρ={r['max_pairwise_correlation']}")
    lines.append(f"paper balance: ${h['pnl']['paper_balance_usd']:.2f}")
    lines.append(f"MTD API: ${h['api_spend_mtd']['total_usd']:.4f} "
                 f"({h['api_spend_mtd']['total_calls']} calls)")
    lines.append(f"agent_actions in last 5: {len(h['agent_actions_recent'])}")
    return "\n".join(lines)


# ---------- new routes ----------

@app.get("/api/positions/live.sse")
async def live_positions_sse():
    """Server-Sent Events stream: one JSON event per open position every 5 seconds."""

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                from lib.paper_engine import get_public_price  # noqa: PLC0415
            except Exception:
                get_public_price = None  # type: ignore

            positions = _q(
                "SELECT id, asset, direction, entry_price, stop_loss, take_profit, "
                "leverage, quantity FROM trades WHERE status='open'"
            )
            for pos in positions:
                try:
                    asset = pos.get("asset", "")
                    entry = float(pos.get("entry_price") or 0)
                    qty = float(pos.get("quantity") or 0)
                    direction = pos.get("direction", "long")
                    sl = pos.get("stop_loss")
                    tp = pos.get("take_profit")

                    mark: float | None = None
                    if get_public_price is not None:
                        try:
                            mark = await asyncio.get_event_loop().run_in_executor(
                                None, get_public_price, asset
                            )
                        except Exception:
                            mark = None

                    if mark is None:
                        mark = entry  # fallback: no price change

                    sign = 1 if direction == "long" else -1
                    unrealized_pnl = (mark - entry) * qty * sign

                    distance_to_sl_pct: float | None = None
                    if sl is not None:
                        try:
                            distance_to_sl_pct = round(abs(mark - float(sl)) / mark * 100, 3)
                        except Exception:
                            pass

                    distance_to_tp_pct: float | None = None
                    if tp is not None:
                        try:
                            distance_to_tp_pct = round(abs(mark - float(tp)) / mark * 100, 3)
                        except Exception:
                            pass

                    payload = {
                        "id": pos.get("id"),
                        "asset": asset,
                        "direction": direction,
                        "entry_price": entry,
                        "mark_price": round(mark, 6),
                        "unrealized_pnl": round(unrealized_pnl, 4),
                        "distance_to_sl_pct": distance_to_sl_pct,
                        "distance_to_tp_pct": distance_to_tp_pct,
                        "leverage": pos.get("leverage"),
                        "quantity": qty,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health/poll.json", response_class=JSONResponse)
def health_poll():
    """Cached (10s) wrapper around health()."""
    now = time.time()
    if _poll_cache["data"] and now - _poll_cache["ts"] < _POLL_TTL:
        return _poll_cache["data"]
    data = health()
    _poll_cache.update({"ts": now, "data": data})
    return data


@app.post("/api/halt", response_class=JSONResponse)
async def halt_trading(request: Request):
    """Kill-switch: halt trading. Localhost only."""
    host = request.client.host
    if host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_state(key, value) VALUES('trading_halted','true')"
        )
        conn.commit()
    finally:
        conn.close()
    _poll_cache["data"] = None  # force cache bust
    return {"ok": True, "halted": True}


@app.post("/api/resume", response_class=JSONResponse)
async def resume_trading(request: Request):
    """Resume trading after halt. Localhost only."""
    host = request.client.host
    if host not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_state(key, value) VALUES('trading_halted','false')"
        )
        conn.commit()
    finally:
        conn.close()
    _poll_cache["data"] = None  # force cache bust
    return {"ok": True, "halted": False}


@app.get("/positions", response_class=HTMLResponse)
def positions_page(request: Request):
    rows = _q("SELECT * FROM trades WHERE status='open' ORDER BY opened_at DESC")
    return TEMPLATES.TemplateResponse(
        "positions.html", {"request": request, "positions": rows}
    )


@app.get("/risk", response_class=HTMLResponse)
def risk_page(request: Request):
    risk_snapshot = _qone(
        "SELECT * FROM portfolio_risk_snapshots ORDER BY id DESC LIMIT 1"
    )

    open_trades = _q(
        "SELECT entry_price, quantity, leverage FROM trades WHERE status='open' AND pillar='market'"
    )
    gross_notional = sum(
        float(t.get("entry_price") or 0)
        * float(t.get("quantity") or 0)
        * float(t.get("leverage") or 1)
        for t in open_trades
    )

    params: dict = {}
    try:
        params = json.loads(
            (Path(PROJECT_ROOT) / "config" / "risk_params.json").read_text()
        )
    except Exception:
        pass

    capital_row = _qone("SELECT value FROM system_state WHERE key='paper_balance_usd'")
    capital = float((capital_row or {}).get("value", 500) or 500)

    exposure_pct = (gross_notional / capital * 100) if capital > 0 else 0.0

    overrides = params.get("paper_mode_overrides", {})
    max_exposure = overrides.get(
        "max_portfolio_exposure_pct",
        params.get("market_trading", {}).get("max_portfolio_exposure_pct", 30),
    )

    corr_matrix_json: str | None = None
    try:
        row = _qone(
            "SELECT matrix_json FROM correlation_matrix_daily ORDER BY date DESC LIMIT 1"
        )
        if row:
            corr_matrix_json = row.get("matrix_json")
    except Exception:
        pass

    return TEMPLATES.TemplateResponse(
        "risk.html",
        {
            "request": request,
            "risk_snapshot": risk_snapshot,
            "exposure_pct": round(exposure_pct, 2),
            "max_exposure_pct": max_exposure,
            "capital": capital,
            "gross_notional": round(gross_notional, 2),
            "corr_matrix_json": corr_matrix_json,
        },
    )


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request):
    from lib.perf_metrics import compute_metrics  # noqa: PLC0415

    closed_trades = _q(
        "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at ASC"
    )
    daily_rows = _q("SELECT * FROM daily_pnl ORDER BY date ASC")
    metrics = compute_metrics(closed_trades, daily_rows)

    strategy_attr = _q(
        "SELECT * FROM strategy_performance ORDER BY total_pnl_usd DESC LIMIT 20"
    )
    asset_attr = _q(
        "SELECT asset, COUNT(*) AS n, SUM(pnl_usd) AS total_pnl "
        "FROM trades WHERE status='closed' GROUP BY asset ORDER BY total_pnl DESC LIMIT 20"
    )
    direction_attr = _q(
        "SELECT direction, COUNT(*) AS n, SUM(pnl_usd) AS total_pnl "
        "FROM trades WHERE status='closed' GROUP BY direction"
    )

    equity_labels = [r["date"] for r in daily_rows if r.get("ending_capital")]
    equity_values = [float(r["ending_capital"]) for r in daily_rows if r.get("ending_capital")]

    return TEMPLATES.TemplateResponse(
        "performance.html",
        {
            "request": request,
            "metrics": metrics,
            "strategy_attr": strategy_attr,
            "asset_attr": asset_attr,
            "dir_attr": direction_attr,
            "daily_rows": daily_rows,
            "equity_labels": equity_labels,
            "equity_values": equity_values,
        },
    )


@app.get("/signals", response_class=HTMLResponse)
def signals_page(request: Request):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _count(sql: str) -> int:
        row = _qone(sql)
        return int(list(row.values())[0]) if row else 0

    raw_signals = _count(
        "SELECT COUNT(*) AS n FROM signals WHERE timestamp >= datetime('now','-24 hours')"
    )
    risk_checks = _count(
        "SELECT COUNT(*) AS n FROM signals WHERE signal_type='risk_check' "
        "AND timestamp >= datetime('now','-24 hours')"
    )
    risk_passed = _count(
        "SELECT COUNT(*) AS n FROM signals WHERE signal_type='risk_check' AND acted_on=1 "
        "AND timestamp >= datetime('now','-24 hours')"
    )
    executed = _count(
        "SELECT COUNT(*) AS n FROM trades WHERE opened_at >= datetime('now','-24 hours')"
    )

    recent_signals = _q("SELECT * FROM signals ORDER BY id DESC LIMIT 50")

    alerts_data: dict = {}
    alerts_path = (
        Path(PROJECT_ROOT) / "data" / "signals" / today / "alerts.json"
    )
    if alerts_path.exists():
        try:
            alerts_data = json.loads(alerts_path.read_text())
        except Exception:
            alerts_data = {}

    alerts_list = alerts_data.get("alerts", []) if isinstance(alerts_data, dict) else []

    return TEMPLATES.TemplateResponse(
        "signals.html",
        {
            "request": request,
            "raw_signals": raw_signals,
            "risk_checks": risk_checks,
            "risk_passed": risk_passed,
            "executed": executed,
            "recent_signals": recent_signals,
            "alerts_count": len(alerts_list),
            "alerts_data": alerts_data,
        },
    )


@app.get("/news", response_class=HTMLResponse)
def news_page(request: Request):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    regime: dict | None = None
    regime_path = Path(PROJECT_ROOT) / "data" / "memory" / "market_regime.json"
    if regime_path.exists():
        try:
            regime = json.loads(regime_path.read_text())
        except Exception:
            pass

    news_items: list = []
    news_path = Path(PROJECT_ROOT) / "data" / "signals" / today / "news.json"
    if news_path.exists():
        try:
            news_items = json.loads(news_path.read_text())
        except Exception:
            pass

    news_signals: dict = {}
    ns_path = (
        Path(PROJECT_ROOT) / "data" / "signals" / today / "news_signals.json"
    )
    if ns_path.exists():
        try:
            news_signals = json.loads(ns_path.read_text())
        except Exception:
            pass

    return TEMPLATES.TemplateResponse(
        "news.html",
        {
            "request": request,
            "regime": regime,
            "news_items": news_items,
            "news_signals": news_signals,
        },
    )


@app.get("/execution", response_class=HTMLResponse)
def execution_page(request: Request):
    rows: list = []
    try:
        rows = _q(
            """SELECT t.id, t.asset, t.direction, t.opened_at, t.entry_price,
                      eq.arrival_price, eq.fill_price, eq.slippage_bps, eq.venue
               FROM trades t
               LEFT JOIN execution_quality eq ON eq.trade_id = t.id
               WHERE eq.trade_id IS NOT NULL
               ORDER BY t.opened_at DESC LIMIT 100"""
        )
    except Exception:
        rows = []
    return TEMPLATES.TemplateResponse(
        "execution.html", {"request": request, "rows": rows}
    )


@app.get("/m", response_class=HTMLResponse)
def mobile_page(request: Request):
    halted = _qone("SELECT value FROM system_state WHERE key='trading_halted'") or {}
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = _qone(
        "SELECT SUM(pnl_usd) AS pnl, COUNT(*) AS n FROM trades WHERE date(closed_at)=?",
        (today_iso,),
    ) or {}
    open_count = _qone("SELECT COUNT(*) AS n FROM trades WHERE status='open'") or {}
    paper_balance = _qone(
        "SELECT value FROM system_state WHERE key='paper_balance_usd'"
    )

    # Daily drawdown pct from daily_pnl table
    daily_pnl_row = _qone(
        "SELECT ending_capital, realized_pnl FROM daily_pnl WHERE date=?",
        (today_iso,),
    ) or {}
    daily_drawdown_pct = 0.0
    ending_cap = float(daily_pnl_row.get("ending_capital") or 0)
    realized = float(daily_pnl_row.get("realized_pnl") or 0)
    if ending_cap > 0 and realized < 0:
        daily_drawdown_pct = round(abs(realized) / ending_cap * 100, 2)

    consecutive = _qone("SELECT value FROM system_state WHERE key='consecutive_losses'")

    return TEMPLATES.TemplateResponse(
        "mobile.html",
        {
            "request": request,
            "halted": (halted.get("value") == "true"),
            "daily_pnl": daily.get("pnl") or 0,
            "daily_count": int(daily.get("n") or 0),
            "daily_dd_pct": daily_drawdown_pct,
            "open_count": int(open_count.get("n") or 0),
            "paper_balance_usd": float(
                (paper_balance or {}).get("value", 0) or 0
            ),
            "consecutive_losses": int((consecutive or {}).get("value", "0") or 0),
        },
    )


def main():
    import uvicorn  # type: ignore
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
