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


def _heartbeat(job: str) -> None:
    """Write last_cron_at + last_cron_job to system_state at the start of every cron.

    P0 observability: without this we have no way to tell if a cron stopped firing.
    A separate dead-man check in news_scan (every 15min) reads these fields and
    alerts the user if market_scan hasn't checked in for >2 hours.
    """
    try:
        sys.path.insert(0, "/app")
        from lib.db import get_connection, set_system_state
        from datetime import datetime as _dt, timezone as _tz
        conn = get_connection()
        try:
            now = _dt.now(_tz.utc).isoformat()
            set_system_state(conn, "last_cron_at", now)
            set_system_state(conn, "last_cron_job", job)
            set_system_state(conn, f"last_cron_at_{job}", now)
        finally:
            conn.close()
    except Exception as e:
        print(f"  [heartbeat-failed] {e}")


def _dead_man_check(max_stale_minutes: int = 120) -> None:
    """Alert if market_scan hasn't checked in within `max_stale_minutes`.

    Called from news_scan (every 15min). Watches market_scan specifically because
    market_scan is the trade-generating cron — if it's silent, the system is
    offline even if news_scan is running. Idempotent: writes
    system_state.last_dead_man_alert_at to avoid spamming Telegram.
    """
    try:
        sys.path.insert(0, "/app")
        from lib.db import get_connection, get_system_state, set_system_state
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        conn = get_connection()
        try:
            last = get_system_state(conn, "last_cron_at_market_scan")
            if not last:
                return  # first deploy, no baseline yet
            ts = _dt.fromisoformat(last.replace("Z", "+00:00"))
            age_min = (_dt.now(_tz.utc) - ts).total_seconds() / 60
            if age_min < max_stale_minutes:
                return  # alive
            last_alert = get_system_state(conn, "last_dead_man_alert_at")
            if last_alert:
                last_alert_ts = _dt.fromisoformat(last_alert.replace("Z", "+00:00"))
                if (_dt.now(_tz.utc) - last_alert_ts).total_seconds() < 3600:
                    return  # already alerted in last hour
            _notify(
                f"🚨 <b>DEAD-MAN ALERT</b>\nmarket_scan has not run for "
                f"{age_min:.0f} minutes (last: {last}). Modal cron may be off-air."
            )
            set_system_state(conn, "last_dead_man_alert_at", _dt.now(_tz.utc).isoformat())
        finally:
            conn.close()
    except Exception as e:
        print(f"  [dead-man-failed] {e}")


def _pm_guard_ok() -> bool:
    """Refuse to run the PM hot-path when tracked_accounts is empty.

    Background: the design intent is to copy curated whale wallets; without
    them, the system falls back to a confluence heuristic that synthesises
    edges from price patterns alone (the Aston Villa pattern). The Stage 1
    fix already gates _paper_heuristic_estimate, but this guard provides
    defence in depth: if wallets haven't been discovered, the PM block
    short-circuits entirely.

    Telegram-throttle: warn AT MOST ONCE every 24 hours. Previous version
    used a module-level _PM_GUARD_WARNED flag, but Modal spawns a fresh
    container per cron tick — so that flag reset every hour and the user
    got spammed. State is now persisted to system_state.last_pm_empty_warn_at
    so the throttle survives container restarts.
    """
    try:
        with open("/app/config/polymarket_accounts.json") as f:
            cfg = json.load(f)
        tracked = cfg.get("tracked_accounts", []) or []
        if tracked:
            return True
    except Exception as e:
        print(f"  [pm-guard] could not read polymarket_accounts.json: {e} — allowing PM block")
        return True

    # tracked_accounts is empty. Skip the PM block; warn at most once per 24h.
    print(f"  [pm-guard] skipping PM block — tracked_accounts empty")
    try:
        sys.path.insert(0, "/app")
        from lib.db import get_connection, get_system_state, set_system_state
        from datetime import datetime as _dt, timezone as _tz
        conn = get_connection()
        try:
            last = get_system_state(conn, "last_pm_empty_warn_at")
            now = _dt.now(_tz.utc)
            should_warn = True
            if last:
                try:
                    ts = _dt.fromisoformat(last.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() < 24 * 3600:
                        should_warn = False
                except (ValueError, AttributeError):
                    pass
            if should_warn:
                _notify(
                    "⚠️ <b>PM hot-path SKIPPED</b>\n"
                    "<i>tracked_accounts is empty.</i> Run discover_wallets.py "
                    "(weekly cron Sun 12:00 UTC) or trigger manually.\n"
                    "<i>(One warning per 24h.)</i>"
                )
                set_system_state(conn, "last_pm_empty_warn_at", now.isoformat())
        finally:
            conn.close()
    except Exception as e:
        # If DB throttle fails for any reason, fall back to silent skip
        # rather than spamming.
        print(f"  [pm-guard] warn-throttle failed (suppressing alert): {e}")
    return False


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
    # PYTHONPATH=/app so `from lib.X` and `from config import ...` resolve in
    # subprocess'd skill scripts.
    # PAPER_MODE=true is the default during the paper trading phase — secrets
    # may override to "false" later when going live, but until then, the paper
    # engine short-circuits in execution_engine before any OKX call.
    .env({
        "PYTHONPATH": "/app",
        "PAPER_MODE": "true",
        "PAPER_STARTING_BALANCE": "500",
    })
    .add_local_dir("lib", remote_path="/app/lib")
    .add_local_dir("config", remote_path="/app/config")
    # Skill scripts compute PROJECT_ROOT by walking 4 `..` from their dirname.
    # Locally that crosses the `.claude` layer to land on the repo root. To
    # match that depth in Modal, preserve the `.claude/` layer: scripts at
    # /app/.claude/skills/X/scripts/Y.py walk up to /app correctly.
    .add_local_dir(".claude/skills", remote_path="/app/.claude/skills")
    .add_local_dir("memory", remote_path="/app/memory")
)

# Secrets (configure in Modal dashboard)
# trading-broker-keys must include:
#   ─── Mode switches ───
#   BROKER_MODE=demo|live|synthetic     — single dispatch flag (preferred)
#   PAPER_MODE=true|false               — legacy fallback, used only if BROKER_MODE unset
#   PAPER_STARTING_BALANCE=500          — virtual capital for synthetic mode
#   PAPER_PRICE_EXCHANGE=okx            — public exchange for prices in synthetic mode
#   ─── Per-asset-class broker overrides (optional; defaults in lib/brokers/router.py) ───
#   CRYPTO_PERP_BROKER=okx              — default
#   STOCKS_BROKER=alpaca                — default
#   FOREX_BROKER=oanda                  — default
#   BONDS_BROKER=alpaca                 — default (bond ETFs)
#   ─── OKX (crypto perps) ───
#   OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE  — demo or live; OKX_DEMO toggles
#   OKX_DEMO=true|false                 — true = ccxt.set_sandbox_mode(True)
#   OKX_REGION=global|eu                — 'eu' = ccxt.myokx (my.okx.com); MiCA
#                                          EU users MUST set 'eu' or auth 50119s.
#   ─── Alpaca (stocks + bond ETFs + crypto spot) ───
#   ALPACA_KEY_ID/ALPACA_SECRET_KEY     — paper or live (separate keysets!)
#   ALPACA_PAPER=true|false             — true = paper-api.alpaca.markets
#   ALPACA_DATA_FEED=iex|sip            — 'iex' free, 'sip' paid (default iex)
#   ─── OANDA (forex) ───
#   OANDA_API_TOKEN                     — Personal Access Token from account portal
#   OANDA_ACCOUNT_ID                    — e.g. 101-001-12345678-001
#   OANDA_PRACTICE=true|false           — true = fxpractice endpoint
secrets = [
    modal.Secret.from_name("trading-broker-keys"),       # All broker keys + MODE flags
    modal.Secret.from_name("trading-data-keys"),         # ALPHA_VANTAGE, FINNHUB, CMC, MARKETAUX, FRED
    modal.Secret.from_name("trading-ai-keys"),           # ANTHROPIC_API_KEY (PERPLEXITY_API_KEY optional)
    modal.Secret.from_name("trading-notification-keys"), # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
]

# Persistent volume holds: data/db/trading.db (strategy_registry, trades, signals,
# api_costs, system_state), data/signals/<date>/ outputs, data/memory/ caches,
# data/reports/ PDFs. Without this, every cron container starts with an empty DB
# — no strategies registered, no trade history, nothing carries between runs.
data_volume = modal.Volume.from_name("trading-data", create_if_missing=True)
volumes = {"/app/data": data_volume}


# ============================================================
# CRON JOBS - The autonomous backbone
# ============================================================

@app.function(
    image=image,
    secrets=secrets,
    volumes=volumes,
    schedule=modal.Cron("*/15 * * * *"),  # Every 15 minutes
    timeout=300,
)
def news_scan():
    """Check for breaking news requiring immediate action.

    Also serves as the dead-man check for market_scan (every 15min cadence
    means we'll notice within 15min if market_scan stops firing).
    """
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running news scan...")
    _heartbeat("news_scan")
    _dead_man_check(max_stale_minutes=120)

    news_base = "/app/.claude/skills/news-monitor/scripts"
    _run(f"{news_base}/news_aggregator.py", timeout=120)
    _run(f"{news_base}/geopolitical_scanner.py", timeout=60)
    _run(f"{news_base}/sentiment_scorer.py", timeout=120)
    r = _run(f"{news_base}/urgency_classifier.py", "--emit-setups", timeout=60)

    # If any urgent setups emitted, run the hot path immediately
    if r["ok"] and "urgent=true" in (r["stdout"] or ""):
        print("  URGENT news detected → running immediate confluence + alerts + pipeline")
        _run("/app/.claude/skills/confluence-engine/scripts/confluence_detector.py", timeout=120)
        _run("/app/.claude/skills/confluence-engine/scripts/score_setup.py", timeout=60)
        _run("/app/.claude/skills/confluence-engine/scripts/alert_generator.py", timeout=60)
        _run("/app/.claude/skills/execute-trade/scripts/pipeline_runner.py", timeout=180)
        _notify(f"⚡ URGENT news-driven trade evaluated at {timestamp}")

    # PM wallet activity poll — cheap, no LLM. Catches new sharp-money entries
    # between hourly market_scan PM passes.
    pm = "/app/.claude/skills/polymarket-bet/scripts"
    _run(f"{pm}/track_wallet_activity.py", timeout=90)

    print(f"[{timestamp}] News scan complete")


@app.function(
    image=image,
    secrets=secrets,
    volumes=volumes,
    schedule=modal.Cron("0 * * * *"),  # Every hour
    timeout=600,
)
def market_scan():
    """Full market scan + signal detection + confluence check."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running market scan...")
    _heartbeat("market_scan")

    scan = "/app/.claude/skills/market-scan/scripts"
    conf = "/app/.claude/skills/confluence-engine/scripts"
    ex   = "/app/.claude/skills/execute-trade/scripts"
    sig  = "/app/.claude/skills/signal-follow/scripts"
    tv   = "/app/.claude/skills/tradingview-analysis/scripts"

    _run(f"{scan}/fetch_market_data.py", timeout=180)
    _run(f"{scan}/technical_analysis.py", timeout=120)
    _run(f"{scan}/support_resistance.py", timeout=60)
    _run(f"{sig}/position_tracker.py", timeout=60)
    # Filter to "paper" since 65 strategies are in paper mode and 0 in live —
    # this is exactly the dataset we're trying to grow during paper trading.
    _run(f"{scan}/screener.py", "--mode-filter", "paper", timeout=180)
    # TV pull scanner: multi-TF alignment for the whole watchlist. Runs in
    # ccxt-fallback mode here (no MCP in Modal). Output lands in tv_pull.json
    # which confluence_detector's glob loader picks up automatically.
    _run(f"{tv}/tv_pull_scanner.py", timeout=180)
    _run(f"{conf}/confluence_detector.py", timeout=120)
    _run(f"{conf}/score_setup.py", timeout=60)
    # alert_generator merges scored confluences with screener entry/SL/TP into alerts.json
    _run(f"{conf}/alert_generator.py", timeout=60)
    # pipeline_runner reads alerts.json, runs each through risk_gate → order_builder → executor
    _run(f"{ex}/pipeline_runner.py", timeout=180)
    _run(f"{ex}/position_monitor.py", timeout=60)

    # Portfolio-level risk snapshot after positions settle. Cheap (under 30s
    # even with 10+ open positions) and emits Telegram alerts on VaR/correlation
    # breaches. Persists to portfolio_risk_snapshots for the daily report.
    rc = "/app/.claude/skills/risk-check/scripts"
    _run(f"{rc}/portfolio_risk_runner.py", timeout=120)

    # Polymarket pillar — full hot-path. Cheap unless candidates clear the
    # confluence gate, in which case Perplexity fires (capped at PM_MAX_LLM_CALLS).
    if _pm_guard_ok():
        pm = "/app/.claude/skills/polymarket-bet/scripts"
        _run(f"{pm}/discover_markets.py", timeout=120)
        _run(f"{pm}/track_wallet_activity.py", timeout=90)
        _run(f"{pm}/signal_engine.py", timeout=60)
        _run(f"{pm}/estimate_probability.py", timeout=300)
        _run(f"{pm}/risk_gate_pm.py", timeout=60)
        # Polymarket Specialist veto layer — kills Aston Villa pattern at source.
        # Cheap (~$0.003/bet on Sonnet 4.6 with cache hits).
        _run(f"{pm}/brain_pm_sanity_check.py", timeout=120)
        _run(f"{pm}/execute_bet.py", timeout=120)

    print(f"[{timestamp}] Market scan complete")


@app.function(
    image=image,
    secrets=secrets,
    volumes=volumes,
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
    _heartbeat("opus_daily_brief")

    news = "/app/.claude/skills/news-monitor/scripts"
    # Step 0: Free-tier data feeds (Workstream 2 Phase A). Cheap, no API cost.
    # FRED needs FRED_API_KEY in secrets; the rest run without keys.
    _run(f"{news}/fred_macro.py", timeout=120)
    _run(f"{news}/defillama_tvl.py", timeout=120)
    _run(f"{news}/econ_calendar.py", timeout=120)
    # Step 1: Refresh Perplexity research log (six topics, each independent).
    _run(f"{news}/research_log.py", timeout=300)
    # Step 2: Single Opus 4.7 call that consumes the research + open positions
    #         + closed trades + market regime, and writes the daily brief.
    _run(f"{news}/opus_daily_review.py", timeout=300)
    # Step 3: one-line Haiku status heartbeat (~$0.001/day). Piggybacks on
    # opus_daily_brief because Modal free tier is at the 5-cron limit; the
    # heartbeat is naturally daily-cadence so this is the right slot.
    _run("/app/.claude/skills/performance-report/scripts/heartbeat_summary.py", timeout=60)

    print(f"[{timestamp}] Opus 4.7 daily brief complete")


# NOTE: nightly_learning merged into weekly_review to stay under Modal's 5-cron
# free-plan limit. Defined as manual-trigger only here. Tuner runs hourly inside
# market_scan; promotion gate runs weekly.
@app.function(image=image, secrets=secrets, volumes=volumes, timeout=1800)
def nightly_learning():
    """Nightly learning — manual trigger only (no cron). Use weekly_review instead."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running nightly learning pass (manual)...")
    _heartbeat("nightly_learning")
    _run("/app/lib/strategy_tuner.py", "--all", timeout=300)
    _run("/app/lib/backtester.py", "--promote-all", "--days", "90", timeout=1500)
    _notify(f"🌙 Nightly learning pass complete at {timestamp}")


# NOTE: polymarket_scan stays manual-trigger only to keep within Modal's 5-cron
# free-plan limit. The PM pipeline is hooked into existing crons:
#   news_scan       (every 15 min) → wallet activity poll
#   market_scan     (hourly)       → full PM hot-path
#   daily_report    (21:00 UTC)    → late-stage convergence sweep
#   weekly_review   (Sun 12:00)    → wallet leaderboard refresh
# This function is the same hot-path callable on demand from the slash command.
@app.function(image=image, secrets=secrets, volumes=volumes, timeout=900)
def polymarket_scan():
    """Polymarket pipeline — manual trigger (also reused from cron hooks)."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Polymarket scan starting")
    _heartbeat("polymarket_scan")
    if not _pm_guard_ok():
        print(f"[{timestamp}] Polymarket scan skipped — tracked_accounts empty")
        return
    pm = "/app/.claude/skills/polymarket-bet/scripts"
    _run(f"{pm}/discover_markets.py", timeout=120)
    _run(f"{pm}/track_wallet_activity.py", timeout=120)
    _run(f"{pm}/signal_engine.py", timeout=60)
    _run(f"{pm}/estimate_probability.py", timeout=300)
    _run(f"{pm}/risk_gate_pm.py", timeout=60)
    _run(f"{pm}/brain_pm_sanity_check.py", timeout=120)
    _run(f"{pm}/execute_bet.py", timeout=120)
    _notify(f"🎯 Polymarket scan complete at {timestamp[:16]}")
    print(f"[{timestamp}] Polymarket scan complete")


@app.function(
    image=image,
    secrets=secrets,
    volumes=volumes,
    schedule=modal.Cron("0 21 * * *"),  # Daily at 21:00 UTC
    timeout=600,
)
def daily_report():
    """Generate daily P&L report and run self-improvement post-mortems."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Generating daily report...")
    _heartbeat("daily_report")

    # Refresh strategy_performance aggregates from the full trade journal so
    # any trades closed outside position_monitor (e.g. SQL patches) are
    # reflected before reporting or self-improve reads the registry.
    try:
        sys.path.insert(0, "/app")
        from lib.strategy_tuner import refresh_all_performance
        refresh_all_performance()
        print("[daily_report] strategy_performance refreshed")
    except Exception as e:
        print(f"[daily_report] strategy_performance refresh failed (non-fatal): {e}")

    perf = "/app/.claude/skills/performance-report/scripts"
    imp  = "/app/.claude/skills/self-improve/scripts"

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

    # Opus 4.7 desk synthesis — full multi-agent end-of-day brief. Replaces
    # the manual paste loop for trade reviews. Sonnet critic red-teams the
    # synth output. Falls back to a heuristic skeleton when budget cap hit.
    news = "/app/.claude/skills/news-monitor/scripts"
    _run(f"{news}/brain_daily_synthesis.py", timeout=240)

    # Resolve any PM bets whose markets settled overnight, credit paper balance.
    pm = "/app/.claude/skills/polymarket-bet/scripts"
    _run(f"{pm}/pm_resolver.py", timeout=120)

    # Late-stage Polymarket convergence sweep — concentrate on markets at
    # 90-95c resolving in 1-7 days. Reuses the standard PM pipeline with a
    # tighter pre-filter.
    if _pm_guard_ok():
        _run(f"{pm}/discover_markets.py", timeout=120)
        _run(f"{pm}/signal_engine.py", timeout=60)
        _run(f"{pm}/estimate_probability.py", timeout=300)
        _run(f"{pm}/risk_gate_pm.py", timeout=60)
        _run(f"{pm}/brain_pm_sanity_check.py", timeout=120)
        _run(f"{pm}/execute_bet.py", timeout=120)

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
    volumes=volumes,
    schedule=modal.Cron("0 12 * * 0"),  # Sunday at 12:00 UTC
    timeout=900,
)
def weekly_review():
    """Weekly performance review, strategy tuning, hypothesis generation."""
    os.chdir("/app")
    timestamp = datetime.now(timezone.utc).isoformat()
    print(f"[{timestamp}] Running weekly review...")
    _heartbeat("weekly_review")

    perf = "/app/.claude/skills/performance-report/scripts"
    imp  = "/app/.claude/skills/self-improve/scripts"
    sig  = "/app/.claude/skills/signal-follow/scripts"

    _run(f"{perf}/performance_metrics.py", "--period", "weekly", timeout=120)
    _run(f"{perf}/generate_weekly_report.py", timeout=180)
    _run("/app/lib/strategy_tuner.py", "--all", timeout=300)
    _run(f"{sig}/skill_scorer.py", timeout=60)
    # Hypothesis generation honors the loop circuit breaker via system_state
    _run(f"{imp}/hypothesis_generator.py", "--auto-apply", timeout=600)
    # Newly proposed strategies sit at mode=backtest — evaluate them immediately
    _run("/app/lib/backtester.py", "--promote-all", "--days", "90", timeout=1800)
    # P3: apply the promotion gate so qualifying strategies move backtest→paper
    # automatically each week. Hurdles enforced in lib/strategy_promotion.py.
    _run("/app/lib/strategy_promotion.py", "--apply", timeout=120)

    # Polymarket: weekly leaderboard refresh + wallet-graph clustering. Updates
    # config/polymarket_accounts.json::tracked_accounts.
    _run("/app/.claude/skills/polymarket-bet/scripts/discover_wallets.py", timeout=600)

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

@app.function(image=image, secrets=secrets, volumes=volumes, timeout=300)
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

    tv = "/app/.claude/skills/tradingview-analysis/scripts"
    _run(f"{tv}/alert_parser.py", "--input", str(alert_dir / "tv_alert.json"), timeout=60)
    _run(f"{tv}/indicator_mapper.py", timeout=60)
    _run("/app/.claude/skills/confluence-engine/scripts/confluence_detector.py", timeout=120)
    r_risk = _run("/app/.claude/skills/risk-check/scripts/risk_gate.py", timeout=60)
    if r_risk["ok"]:
        _run("/app/.claude/skills/execute-trade/scripts/execution_engine.py", "--source=tradingview", timeout=120)

    return {"status": "processed", "timestamp": timestamp}


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=60)
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


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=300)
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

    r_risk = _run("/app/.claude/skills/risk-check/scripts/risk_gate.py", "--input", str(manual_path), timeout=60)
    if not r_risk["ok"]:
        return {"status": "risk_rejected", "detail": r_risk["stderr"]}
    r_ex = _run("/app/.claude/skills/execute-trade/scripts/execution_engine.py", "--source=manual", "--input", str(manual_path), timeout=120)
    return {"status": "executed" if r_ex["ok"] else "exec_failed", "stdout": r_ex["stdout"][-500:]}


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=60)
@modal.fastapi_endpoint(method="GET")
def readiness():
    """Live-trading readiness checklist. Returns pass/fail for each gate."""
    os.chdir("/app")
    sys.path.insert(0, "/app")
    try:
        from lib.live_readiness import is_ready_for_live, format_report
        passed, checks = is_ready_for_live()
        return {
            "ready": passed,
            "status": "PASS" if passed else "FAIL",
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"ready": False, "status": "ERROR", "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()}


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=60)
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


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=60)
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


@app.function(image=image, secrets=secrets, volumes=volumes, timeout=60)
@modal.fastapi_endpoint(method="POST")
def telegram_webhook(data: dict):
    """Receive Telegram bot updates and dispatch commands.

    Register this URL with Telegram once after deploying:
      curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \\
           -H "Content-Type: application/json" \\
           -d '{"url": "https://<modal-app-url>/telegram-webhook"}'

    Supported commands (send as plain text or with / prefix):
      status update / status / /status  → open positions snapshot
      pnl / /pnl                        → today's realized P&L
      help / /help                      → command list
    """
    os.chdir("/app")
    sys.path.insert(0, "/app")
    try:
        from lib.telegram_bot import handle_update
        handle_update(data)
    except Exception as e:
        print(f"[telegram_webhook] error: {e}")
    # Always return 200 so Telegram doesn't retry
    return {"ok": True}
