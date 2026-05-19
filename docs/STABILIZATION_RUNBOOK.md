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

## Step 2 — Generate OKX demo credentials (≈ 5 min, one-time)

1. Log in at <https://www.okx.com>, then go to **Demo Trading** (top-right menu).
2. Create a virtual portfolio if you don't have one (gives you 10,000 USDT virtual).
3. Open **API → Demo Trading API** (NOT the live keys page).
4. Generate a new key set with `Read` + `Trade` permissions. Save:
   - `OKX_API_KEY`
   - `OKX_SECRET_KEY`
   - `OKX_PASSPHRASE`

> OKX demo trading runs at `https://www.okx.com/api/v5` with a special header.
> `lib/brokers/okx_adapter.py:69` reads `OKX_DEMO` and sets the header
> automatically — no code changes needed.

---

## Step 3 — Add Modal secrets (≈ 3 min, one-time)

Go to Modal dashboard → **Secrets** → edit `trading-broker-keys`. Add or update:

```
BROKER_MODE=demo
OKX_DEMO=true
OKX_API_KEY=<from step 2>
OKX_SECRET_KEY=<from step 2>
OKX_PASSPHRASE=<from step 2>
PAPER_MODE=false        # IMPORTANT: must flip from true → false
```

Why both `BROKER_MODE=demo` and `PAPER_MODE=false`: `broker_mode()` reads
`BROKER_MODE` first; `PAPER_MODE` is a fallback that only matters if
`BROKER_MODE` is unset. Setting both explicitly is defensive.

While you're there, confirm `trading-ai-keys` contains `ANTHROPIC_API_KEY`.
If missing, paste it now — the PM specialist and daily synthesizer won't fire
without it.

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

## Step 5 — Validate first OKX demo trade (≈ next hourly cron tick)

Wait for the next 00-minute UTC hour. Then:

```bash
sqlite3 -header data/db/trading.db \
  "SELECT id, asset, direction, broker, entry_price, opened_at
     FROM trades WHERE status='open' ORDER BY id DESC LIMIT 5;"
```

You're looking for `broker` values like `okx-demo` (or whatever the adapter
stamps) instead of `paper`. If you see `paper`, `BROKER_MODE` didn't make it
into the container — re-check Step 3 + deploy.

Cross-check on OKX: log in to demo trading → Positions tab → confirm a real
position exists with matching size.

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
| Trades opening on `paper` instead of `okx-demo` | `BROKER_MODE` secret value + redeploy |
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
4. At least 1 closed trade per 48h on `broker = 'okx-demo'`
5. No `discovery_method = 'heuristic_paper'` rows in `polymarket_bets` opened after 2026-05-15
6. MTD API spend < $250

Failing any of these blocks the live-money flip discussion.
