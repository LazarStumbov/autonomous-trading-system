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

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, Request  # type: ignore
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse  # type: ignore
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
    # Pretty-print the JSON-ish reasoning column
    reasoning_pretty = t.get("reasoning") or ""
    return TEMPLATES.TemplateResponse(
        "trade_detail.html",
        {"request": request, "trade": t, "reasoning_pretty": reasoning_pretty},
    )


@app.get("/strategies", response_class=HTMLResponse)
def strategies(request: Request):
    rows = _q(
        """SELECT r.id, r.mode, r.source, p.total_trades, p.win_rate, p.profit_factor,
                  p.sharpe_30d, p.last_trade_at,
                  r.tv_trades, r.tv_win_rate, r.tv_severity_passed,
                  r.tv_severity_reason, r.demotion_reason
           FROM strategy_registry r
           LEFT JOIN strategy_performance p ON p.strategy_id = r.id
           ORDER BY r.tv_severity_passed DESC, r.tv_trades DESC, r.id ASC"""
    )
    return TEMPLATES.TemplateResponse("strategies.html", {"request": request, "strategies": rows})


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


def main():
    import uvicorn  # type: ignore
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
