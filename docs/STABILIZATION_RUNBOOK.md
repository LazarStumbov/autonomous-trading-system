# Stabilization Runbook — go from "code shipped" to "running autonomously"

> Use this after merging commit `1bf839b` (or later) and before walking away.
> Each step has a verification command. Don't skip the verifications.

---

## Step 1 — Redeploy Modal (≈ 2 min)

```bash
cd modal && bash deploy.sh
```

**Verify:**
```bash
modal app list | grep autonomous-trading-system
```
Should show `running`. If not, check `modal app logs autonomous-trading-system` for the build error.

---

## Step 2 — Generate paper-broker credentials (≈ 15 min, one-time)

You need **three** broker accounts — one per asset class. All free, all paper.
Sign up from whichever country (Spain or Bulgaria both work fine for paper).

### 2a — OKX Demo (crypto perpetuals)
1. Log in at <https://www.okx.com> → **Demo Trading** (top-right menu).
2. Create a virtual portfolio (gives you 10,000 USDT virtual).
3. **API → Demo Trading API** (NOT live). Generate keys with `Read` + `Trade`.
4. Save: `OKX_API_KEY`, `OKX_SECRET_KEY`, `OKX_PASSPHRASE`.

### 2b — Alpaca Paper (stocks + bond ETFs + crypto spot)
1. Sign up at <https://alpaca.markets> (free, no KYC required for paper).
2. **Paper Trading → API Keys** (the URL says `paper-api`). Generate a new key.
3. Default virtual capital: $100,000. You can reset/lower this in the dashboard.
4. Save: `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` (NOT the same as live keys).
5. Data feed: leave at `iex` (free, ~15-min delayed). Upgrade to `sip` later if needed.

### 2c — OANDA fxTrade Practice (forex)
1. Sign up at <https://www.oanda.com/account/login/?source=fxpractice> (free).
2. Account portal → **Manage API Access** → Generate Personal Access Token.
3. From the same page, copy the **Account ID** (looks like `101-001-12345678-001`).
4. Save: `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`.

> All three adapters live in `lib/brokers/{okx,alpaca,oanda}_adapter.py`. The
> per-asset-class router (`lib/brokers/router.py`) picks the right one based
> on the symbol — you don't need to think about this at trade time.

---

## Step 3 — Add Modal secrets (≈ 3 min, one-time)

Go to Modal dashboard → **Secrets** → edit `trading-broker-keys`. Add:

```
# ─── Mode switches ───
BROKER_MODE=demo
PAPER_MODE=false                       # legacy fallback; explicit value is defensive

# ─── OKX (crypto perps) ───
OKX_DEMO=true
OKX_API_KEY=<from step 2a>
OKX_SECRET_KEY=<from step 2a>
OKX_PASSPHRASE=<from step 2a>

# ─── Alpaca (stocks + bond ETFs + crypto spot) ───
ALPACA_PAPER=true
ALPACA_KEY_ID=<from step 2b>
ALPACA_SECRET_KEY=<from step 2b>
ALPACA_DATA_FEED=iex

# ─── OANDA (forex) ───
OANDA_PRACTICE=true
OANDA_API_TOKEN=<from step 2c>
OANDA_ACCOUNT_ID=<from step 2c>
```

Each adapter reads its own keys. The router picks which one to use per symbol.

While you're there, confirm `trading-ai-keys` contains `ANTHROPIC_API_KEY` —
the PM specialist and daily synthesizer won't fire without it.

**Verify creds before deploying:** locally,
```bash
python3 lib/brokers/router.py
```
That runs `auth_test()` on every configured adapter and reports OK/FAIL per
broker. If any FAIL, fix that broker's keys before continuing.

**Re-deploy after secret changes:**
```bash
cd modal && bash deploy.sh
```

---

## Step 4 — Force-trigger market_scan once (≈ 60 sec)

From the Modal dashboard, click `market_scan` → **Run now**.

**Verify** the cron completed cleanly:
```bash
TODAY=$(date -u +%Y-%m-%d)
ls -la "data/signals/$TODAY/" 2>/dev/null
```
Should contain `market_data.json`, `confluences.json`, `alerts.json` (and likely a fresh `portfolio_risk_snapshots` DB row).

**Verify heartbeat landed:**
```bash
sqlite3 data/db/trading.db "SELECT key, value FROM system_state WHERE key LIKE 'last_cron_at%';"
```
Should show `last_cron_at = <recent>` and `last_cron_at_market_scan = <recent>`.

---

## Step 5 — Validate first real-broker trade (≈ next hourly cron tick)

Wait for the next 00-minute UTC hour. Then:

```bash
sqlite3 -header data/db/trading.db \
  "SELECT id, asset, direction, broker, entry_price, opened_at
     FROM trades WHERE status='open' ORDER BY id DESC LIMIT 10;"
```

You're looking for `broker` values like:
- `okx_demo` — crypto perp trade (e.g. `BTC/USDT:USDT`)
- `alpaca_demo` — stock trade (e.g. `SPY`, `NVDA`) or bond ETF (`TLT`)
- `oanda_demo` — forex trade (e.g. `EURUSD`)

If you see `paper` after Step 3, the dispatch is still in synthetic mode —
re-check `BROKER_MODE=demo` in the Modal secret + redeploy.

**Cross-check on each broker:**
- **OKX**: demo trading → Positions tab. Confirm matching position.
- **Alpaca**: paper dashboard → Positions. Confirm matching shares.
- **OANDA**: practice fxTrade → Open Positions. Confirm matching units.

If you see `synthetic` in `broker` for an asset class that should have a real
adapter, the router fell through (likely cause: that broker's `auth_test()`
returned FAIL during startup — re-run `python3 lib/brokers/router.py` locally
with the same env to diagnose).

---

## Step 6 — Verify the brain is firing (≈ next PM cron tick)

The PM specialist runs on every `market_scan` (hourly) and `polymarket_scan` (manual).
The daily synthesizer fires at 21:00 UTC inside `daily_report`.

After the first cron pass that processes a PM candidate:
```bash
sqlite3 -header data/db/trading.db \
  "SELECT timestamp, job, model, ok, ROUND(usd_cost,4) AS cost
     FROM agent_actions ORDER BY id DESC LIMIT 10;"
```

You want to see rows where `job` is `brain_pm_sanity_check` or `brain_daily_synthesis`.
If `agent_actions` is empty after 24 hours, `ANTHROPIC_API_KEY` is missing or
the budget cap is hit. Check:
```bash
sqlite3 data/db/trading.db "SELECT model, COUNT(*), ROUND(SUM(usd_cost),4) FROM api_costs WHERE timestamp LIKE '2026-05-%' GROUP BY model;"
```

---

## Step 7 — Subscribe to the operational signal

You now have three ways to read the system:

1. **One-screen text** (for terminal or curl):
   ```bash
   python3 dashboard/app.py &
   curl -s http://127.0.0.1:8765/health/summary
   ```
2. **Full JSON** (for jq / scripts / monitoring):
   ```bash
   curl -s http://127.0.0.1:8765/health | jq .flags
   ```
3. **Telegram dead-man alerts**: if `market_scan` is silent for >2h, you get a
   message automatically. This is wired into `news_scan` (every 15min).

The single field to watch is `flags.overall_ok`. When that's `true`, walk away.

---

## What to do if something breaks

| Symptom | First check |
|---|---|
| `flags.cron_alive = false` after deploy | Modal cron status page; look for image-build errors |
| `flags.brain_firing = false` after 24h | `trading-ai-keys` secret contains `ANTHROPIC_API_KEY` |
| Telegram dead-man alert fires | Modal app dashboard → app logs for the affected cron |
| Trades opening on `paper` instead of `okx_demo`/`alpaca_demo`/`oanda_demo` | `BROKER_MODE=demo` secret value + redeploy |
| Crypto trades work but stocks/forex go to `synthetic` | Run `python3 lib/brokers/router.py` locally — see which adapter's `auth_test()` fails, fix that broker's keys |
| PM bets still appearing as `heuristic_paper` | Expected behaviour until `discover_wallets.py` (Sun 12:00 UTC) populates `tracked_accounts`. The PM guard short-circuits PM pipeline until then. |

---

## Known follow-ups (not blocking)

- **Backtester `--promote-all`** locally produced only 3 result rows for 2 strategies on the last run. Most strategies failed silently — likely OHLCV data fetch issues for symbols outside the OKX universe. Investigate after Steps 1–7 are green.
- **P4 correlation-cluster veto** in `risk_engine.check_correlated_positions` is deferred — current per-strategy + per-cycle caps satisfy the verification target.
- The `/health` JSON route is local-only (`127.0.0.1:8765`). Exposing it to Modal as a public route is a Step 8 if you want remote dashboards.

---

## Acceptance criteria (30-day soak)

The system is on track when, sampled at random hours:

1. `flags.overall_ok = true`
2. `agent_actions` accumulating ≥ 5 rows/day
3. `last_cron_at_market_scan < 60 min` old
4. At least 1 closed trade per 48h on a real broker (`broker LIKE '%_demo'`)
5. Trade ledger shows non-zero counts across **all three** broker labels (`okx_demo`, `alpaca_demo`, `oanda_demo`) — confirms the multi-asset router is doing its job
6. No `discovery_method = 'heuristic_paper'` rows in `polymarket_bets` opened after 2026-05-15
7. MTD API spend < $250

Failing any of these blocks the live-money flip discussion.
