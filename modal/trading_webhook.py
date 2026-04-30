"""Modal cloud deployment for autonomous trading system.

Runs 24/7 with scheduled cron jobs for market scanning, news monitoring,
Polymarket analysis, and daily/weekly reports.

Deploy: modal deploy modal/trading_webhook.py
"""

import modal
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def _run(script: str, *args: str, timeout: int = 300) -> dict:
    """Execute a pipeline step inside the Modal container. Returns {ok, stdout, stderr}."""
    cmd = [sys.executable, script, *args]
    print(f"  $ {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/app")
        if r.stdout:
            print(r.stdout)
        if r.returncode != 0:
            print(f"  !! exit {r.returncode}: {r.stderr}", flush=True)
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}
    except subprocess.TimeoutExpired:
        print(f"  !! timeout after {timeout}s: {script}")
        return {"ok": False, "stdout": "", "stderr": f"timeout {timeout}s", "code": -1}
    except Exception as e:
        print(f"  !! error: {e}")
        return {"ok": False, "stdout": "", "stderr": str(e), "code": -2}


def _notify(msg: str) -> None:
    """Fire-and-forget Telegram message. Never raises."""
    try:
        sys.path.insert(0, "/app")
        from lib.notifier import send_telegram
        send_telegram(msg)
    except Exception as e:
        print(f"  [notify-failed] {e}")

# Modal app definition
app = modal.App("autonomous-trading-system")

# Docker image with all dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "anthropic>=0.40.0",
        "ccxt>=4.0.0",
        "ta>=0.11.0",
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
        "aiohttp>=3.9.0",
        "python-dotenv>=1.0.0",
        "reportlab>=4.0.0",
        "python-telegram-bot>=20.0",
        "fastapi[standard]>=0.115.0",
    )
    .add_local_dir("lib", remote_path="/app/lib")
    .add_local_dir("config", remote_path="/app/config")
    .add_local_dir(".claude/skills", remote_path="/app/skills")
    .add_local_dir("memory", remote_path="/app/memory")
)

# Secrets (configure in Modal dashboard)
# trading-broker-keys must include:
#   PAPER_MODE=true|false               — internal paper trading switch
#   PAPER_STARTING_BALANCE=500          — virtual capital, default 500 USD
#   PAPER_PRICE_EXCHANGE=okx            — public exchange for prices
#   OKX_API_KEY/SECRET_KEY/PASSPHRASE   — only required when PAPER_MODE=false
#   OKX_DEMO=true|false                 — only matters when PAPER_MODE=false
secrets = [
    modal.Secret.from_name("trading-broker-keys"),       # PAPER_MODE, OKX_*, PAPER_*
    modal.Secret.from_name("trading-data-keys"),         # ALPHA_VANTAGE, FINNHUB, CMC, MARKETAUX
    modal.Secret.from_name("trading-ai-keys"),           # ANTHROPIC_API_KEY (PERPLEXITY_API_KEY optional)
    modal.Secret.from_name("trading-notification-keys"), # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
]


# ============================================================
# CRON JOBS - The autonomous backbone
# ============================================================

@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("*/15 * * * *"),  # Every 15 minutes
    timeout=300,
)
def news_scan():
    """Check for breaking news requiring immediate action."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running news scan...")

    news_base = "/app/skills/news-monitor/scripts"
    _run(f"{news_base}/news_aggregator.py", timeout=120)
    _run(f"{news_base}/geopolitical_scanner.py", timeout=60)
    _run(f"{news_base}/sentiment_scorer.py", timeout=120)
    r = _run(f"{news_base}/urgency_classifier.py", "--emit-setups", timeout=60)

    # If any urgent setups emitted, run the hot path immediately
    if r["ok"] and "urgent=true" in (r["stdout"] or ""):
        print("  URGENT news detected → running immediate confluence + risk + execute")
        _run("/app/skills/confluence-engine/scripts/confluence_detector.py", timeout=120)
        _run("/app/skills/risk-check/scripts/risk_gate.py", timeout=60)
        _run("/app/skills/execute-trade/scripts/execution_engine.py", "--source=news", timeout=120)
        _notify(f"⚡ URGENT news-driven trade evaluated at {timestamp}")

    print(f"[{timestamp}] News scan complete")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 * * * *"),  # Every hour
    timeout=600,
)
def market_scan():
    """Full market scan + signal detection + confluence check."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running market scan...")

    scan = "/app/skills/market-scan/scripts"
    conf = "/app/skills/confluence-engine/scripts"
    risk = "/app/skills/risk-check/scripts"
    ex   = "/app/skills/execute-trade/scripts"
    sig  = "/app/skills/signal-follow/scripts"

    _run(f"{scan}/fetch_market_data.py", timeout=180)
    _run(f"{scan}/technical_analysis.py", timeout=120)
    _run(f"{scan}/support_resistance.py", timeout=60)
    _run(f"{sig}/position_tracker.py", timeout=60)
    # screener.py runs every strategy in live+paper mode against every symbol
    _run(f"{scan}/screener.py", "--mode-filter", "live", timeout=180)
    _run(f"{conf}/confluence_detector.py", timeout=120)
    _run(f"{conf}/score_setup.py", timeout=60)
    # risk_gate reads setups.json, emits a filtered list of approved trades
    r_risk = _run(f"{risk}/risk_gate.py", timeout=60)
    if r_risk["ok"]:
        _run(f"{ex}/execution_engine.py", "--source=market_scan", timeout=180)
        _run(f"{ex}/position_monitor.py", timeout=60)

    print(f"[{timestamp}] Market scan complete")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 8 * * *"),  # Daily at 08:00 UTC — before EU/US sessions open
    timeout=900,
)
def opus_daily_brief():
    """Opus 4.7 morning market brief.

    Runs Perplexity research first to refresh the citation-backed research log,
    then calls Opus 4.7 once to synthesize a structured daily briefing covering
    regime read, watchlist, biases, risk posture, and headline drivers. Output
    lands in data/signals/<date>/opus_daily_brief.json and the markdown mirror
    memory/DAILY-BRIEF.md. The first paragraph is sent to Telegram.
    """
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running Opus 4.7 daily brief...")

    news = "/app/skills/news-monitor/scripts"
    # Step 1: Refresh Perplexity research log (six topics, each independent).
    _run(f"{news}/research_log.py", timeout=300)
    # Step 2: Single Opus 4.7 call that consumes the research + open positions
    #         + closed trades + market regime, and writes the daily brief.
    _run(f"{news}/opus_daily_review.py", timeout=300)

    print(f"[{timestamp}] Opus 4.7 daily brief complete")


# NOTE: nightly_learning merged into weekly_review to stay under Modal's 5-cron
# free-plan limit. Defined as manual-trigger only here. Tuner runs hourly inside
# market_scan; promotion gate runs weekly.
@app.function(image=image, secrets=secrets, timeout=1800)
def nightly_learning():
    """Nightly learning — manual trigger only (no cron). Use weekly_review instead."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running nightly learning pass (manual)...")
    _run("/app/lib/strategy_tuner.py", "--all", timeout=300)
    _run("/app/lib/backtester.py", "--promote-all", "--days", "90", timeout=1500)
    _notify(f"🌙 Nightly learning pass complete at {timestamp}")


# NOTE: polymarket_scan removed from cron schedule — Stage 3, function defined
# below as a manual-trigger only (no schedule) so it doesn't count against the
# 5-cron Modal limit. Re-enable a schedule once Stage 3 lands.
@app.function(image=image, secrets=secrets, timeout=600)
def polymarket_scan():
    """Polymarket scan — Stage 3 stub. Manual trigger only (no cron)."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Polymarket scan (stub — Stage 3 implementation deferred)")
    _run("/app/skills/polymarket-bet/scripts/polymarket_bet_stub.py", timeout=30)


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 21 * * *"),  # Daily at 21:00 UTC
    timeout=600,
)
def daily_report():
    """Generate daily P&L report and run self-improvement post-mortems."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Generating daily report...")

    perf = "/app/skills/performance-report/scripts"
    imp  = "/app/skills/self-improve/scripts"

    # Ingest any Opus reviews the user pasted into reviews/completed/ since
    # yesterday's run. Validated hypotheses land in strategy_hypotheses table
    # at status='pending_backtest' for the nightly_learning pass to evaluate.
    _run(f"{imp}/ingest_trade_review.py", timeout=60)

    _run(f"{perf}/trade_journal.py", timeout=60)
    _run(f"{perf}/pnl_calculator.py", timeout=60)
    _run(f"{perf}/performance_metrics.py", "--period", "daily", timeout=60)
    r_pdf = _run(f"{perf}/generate_daily_report.py", timeout=180)
    _run(f"{imp}/trade_analyzer.py", timeout=120)
    _run(f"{imp}/memory_updater.py", timeout=60)
    # Emit packets for trades closed today so the user can paste them into
    # the Claude UI (subscription) and feed Opus's verdict back via ingest.
    _run(f"{imp}/trade_review_packet.py", timeout=60)

    summary_path = "/app/data/reports/latest_daily_summary.txt"
    summary = ""
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = f.read()[:3500]
    _notify(f"📊 <b>Daily report</b> {timestamp[:10]}\n\n{summary or 'No closed trades today.'}")

    print(f"[{timestamp}] Daily report complete")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 12 * * 0"),  # Sunday at 12:00 UTC
    timeout=900,
)
def weekly_review():
    """Weekly performance review, strategy tuning, hypothesis generation."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running weekly review...")

    perf = "/app/skills/performance-report/scripts"
    imp  = "/app/skills/self-improve/scripts"
    sig  = "/app/skills/signal-follow/scripts"

    _run(f"{perf}/performance_metrics.py", "--period", "weekly", timeout=120)
    _run(f"{perf}/generate_weekly_report.py", timeout=180)
    _run("/app/lib/strategy_tuner.py", "--all", timeout=300)
    _run(f"{sig}/skill_scorer.py", timeout=60)
    # Hypothesis generation honors the loop circuit breaker via system_state
    _run(f"{imp}/hypothesis_generator.py", "--auto-apply", timeout=600)
    # Newly proposed strategies sit at mode=backtest — evaluate them immediately
    _run("/app/lib/backtester.py", "--promote-all", "--days", "90", timeout=1800)

    summary_path = "/app/data/reports/latest_weekly_summary.txt"
    summary = ""
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = f.read()[:3500]
    _notify(f"📆 <b>Weekly review</b> {timestamp[:10]}\n\n{summary or 'Weekly review complete.'}")

    print(f"[{timestamp}] Weekly review complete")


# ============================================================
# WEB ENDPOINTS - For external triggers
# ============================================================

@app.function(image=image, secrets=secrets, timeout=300)
@modal.fastapi_endpoint(method="POST")
def tradingview_alert(data: dict):
    """Receive TradingView webhook alerts."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Validate webhook secret
    expected_secret = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "")
    if data.get("secret") != expected_secret:
        return {"status": "error", "message": "Invalid secret"}

    print(f"[{timestamp}] TradingView alert received: {json.dumps(data)}")

    # Persist the alert for the pipeline to consume
    import pathlib
    alert_dir = pathlib.Path("/app/data/signals") / timestamp[:10]
    alert_dir.mkdir(parents=True, exist_ok=True)
    with open(alert_dir / "tv_alert.json", "w") as f:
        json.dump(data, f)

    tv = "/app/skills/tradingview-analysis/scripts"
    _run(f"{tv}/alert_parser.py", "--input", str(alert_dir / "tv_alert.json"), timeout=60)
    _run(f"{tv}/indicator_mapper.py", timeout=60)
    _run("/app/skills/confluence-engine/scripts/confluence_detector.py", timeout=120)
    r_risk = _run("/app/skills/risk-check/scripts/risk_gate.py", timeout=60)
    if r_risk["ok"]:
        _run("/app/skills/execute-trade/scripts/execution_engine.py", "--source=tradingview", timeout=120)

    return {"status": "processed", "timestamp": timestamp}


@app.function(image=image, secrets=secrets, timeout=60)
@modal.fastapi_endpoint(method="GET")
def status():
    """System health check and current portfolio status."""
    os.chdir("/app")

    sys.path.insert(0, "/app")
    try:
        from lib.db import get_connection, get_system_state, get_open_trades, get_daily_stats, list_strategies
        conn = get_connection()
        try:
            halted = get_system_state(conn, "trading_halted")
            consec = get_system_state(conn, "consecutive_losses")
            daily_pnl = get_system_state(conn, "daily_pnl_usd")
            open_trades = get_open_trades(conn)
            stats = get_daily_stats(conn)
            mode_counts: dict = {}
            for s in list_strategies(conn):
                mode_counts[s["mode"]] = mode_counts.get(s["mode"], 0) + 1
        finally:
            conn.close()
    except Exception as e:
        return {"status": "degraded", "error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

    return {
        "status": "halted" if halted == "true" else "online",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.2.0",
        "trading_halted": halted == "true",
        "consecutive_losses": consec,
        "daily_pnl_usd": daily_pnl,
        "open_trades": len(open_trades),
        "daily_stats": stats,
        "strategies_by_mode": mode_counts,
    }


@app.function(image=image, secrets=secrets, timeout=300)
@modal.fastapi_endpoint(method="POST")
def manual_trade(data: dict):
    """Execute a trade manually via API. Still goes through the risk gate."""
    os.chdir("/app")

    expected_secret = os.getenv("MANUAL_TRADE_SECRET", "")
    if data.get("secret") != expected_secret:
        return {"status": "error", "message": "invalid secret"}

    import pathlib, tempfile
    required = {"symbol", "direction", "entry_price", "stop_loss", "take_profit"}
    if not required.issubset(data.keys()):
        return {"status": "error", "missing": list(required - set(data.keys()))}

    # Write to the pipeline's setups.json with a manual-source marker
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = pathlib.Path("/app/data/signals") / today
    out_dir.mkdir(parents=True, exist_ok=True)
    manual_path = out_dir / "manual_setup.json"
    with open(manual_path, "w") as f:
        json.dump({**data, "source": "manual", "timestamp": datetime.now(timezone.utc).isoformat()}, f)

    r_risk = _run("/app/skills/risk-check/scripts/risk_gate.py", "--input", str(manual_path), timeout=60)
    if not r_risk["ok"]:
        return {"status": "risk_rejected", "detail": r_risk["stderr"]}
    r_ex = _run("/app/skills/execute-trade/scripts/execution_engine.py", "--source=manual", "--input", str(manual_path), timeout=120)
    return {"status": "executed" if r_ex["ok"] else "exec_failed", "stdout": r_ex["stdout"][-500:]}


@app.function(image=image, secrets=secrets, timeout=60)
@modal.fastapi_endpoint(method="POST")
def halt_trading(data: dict):
    """Emergency halt all trading."""
    os.chdir("/app")
    expected_secret = os.getenv("ADMIN_SECRET", "")
    if data.get("secret") != expected_secret:
        return {"status": "error", "message": "invalid secret"}

    sys.path.insert(0, "/app")
    try:
        from lib.db import get_connection, set_system_state
        conn = get_connection()
        try:
            set_system_state(conn, "trading_halted", "true")
        finally:
            conn.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}
    _notify("🛑 <b>TRADING HALTED</b> via admin endpoint")
    return {"status": "halted", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.function(image=image, secrets=secrets, timeout=60)
@modal.fastapi_endpoint(method="POST")
def resume_trading(data: dict):
    """Resume trading after halt."""
    os.chdir("/app")
    expected_secret = os.getenv("ADMIN_SECRET", "")
    if data.get("secret") != expected_secret:
        return {"status": "error", "message": "invalid secret"}

    sys.path.insert(0, "/app")
    try:
        from lib.db import get_connection, set_system_state
        conn = get_connection()
        try:
            set_system_state(conn, "trading_halted", "false")
            set_system_state(conn, "consecutive_losses", "0")
        finally:
            conn.close()
    except Exception as e:
        return {"status": "error", "message": str(e)}
    _notify("✅ Trading resumed via admin endpoint")
    return {"status": "resumed", "timestamp": datetime.now(timezone.utc).isoformat()}
