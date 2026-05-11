---
name: polymarket-bet
description: Polymarket prediction market operations. Smart-money-following pipeline that discovers wallets, detects cluster signals, estimates true probabilities (Perplexity-gated, cached), runs Polymarket-specific risk checks, and executes paper bets by default (live execution gated by PM_LIVE_TRADING). Built around the edge that arbitrage bots can't price: late-stage convergence, low-liquidity retail mispricing, and Théo-style multi-wallet whale clusters.
allowed-tools: Bash, Read, WebSearch, WebFetch
---

# Polymarket Bet Skill

5-layer funnel — most cycles run with **zero LLM calls**. Perplexity only fires
on candidates that pass the heuristic confluence threshold.

## Edge thesis (why this can make money)

| Edge | Why retail/bots miss it |
|---|---|
| **Wallet-graph copy** | Public leaderboards rank single wallets; we cluster by entry-timing overlap to catch Théo-style multi-wallet whales |
| **Cluster-signal premium** | 3+ uncorrelated sharps converging = high signal; bots don't aggregate |
| **Late-stage convergence** | Markets at 90-95c resolving in 1-7 days — retail leaves capital trapped, bots avoid (low edge per $) |
| **Fee-free geopolitical** | Polymarket waives fees on world events — concentrate Kelly there |
| **Cross-market consistency** | Sum of related markets ≠ logical bound; bots only catch obvious pairs |
| **Obscure-market news** | Niche markets get slow-priced; Perplexity research closes the gap |

## When to use
- Hourly via Modal cron (hooked into `market_scan`)
- Every 15 min for wallet activity polling (hooked into `news_scan`)
- Daily 22:00 UTC for late-stage convergence sweep (hooked into `daily_report`)
- Weekly Sunday 12:00 UTC for wallet leaderboard refresh (hooked into `weekly_review`)
- Manual trigger via `/polymarket-scan`

## Pipeline (5 layers)

### Layer 1 — Discovery (zero LLM)
```bash
python3 .claude/skills/polymarket-bet/scripts/discover_markets.py
python3 .claude/skills/polymarket-bet/scripts/discover_wallets.py   # weekly only
```
- `discover_markets.py` → `data/signals/<date>/pm_markets.json` (active markets ≥ $10k liq, normalized)
- `discover_wallets.py` → updates `config/polymarket_accounts.json::tracked_accounts` + `wallet_clusters` with the top 25 sharps after Bayesian shrinkage and bot-suspect filtering

### Layer 2 — Signal generation (zero LLM)
```bash
python3 .claude/skills/polymarket-bet/scripts/track_wallet_activity.py
python3 .claude/skills/polymarket-bet/scripts/signal_engine.py
```
- `track_wallet_activity.py` polls each tracked wallet (last-poll state in `data/memory/pm_wallet_state.json`), emits cluster + conviction signals → `pm_wallet_activity.json`
- `signal_engine.py` aggregates all signals, scores 0-100 per market, ranks → `pm_candidates.json`

| Signal | Max | Trigger |
|---|---|---|
| Smart-money entry | 30 | +30 if cluster (≥2 distinct clusters); else +8-15 single sharp |
| High-conviction sizing | 15 | bet > $5k |
| Late-stage convergence | 25 | yes∈[0.90, 0.97], 24-168h to resolve, liq≥$50k |
| News reprice | 20 | news-monitor urgency≥7 keyword overlap |
| Cross-market inconsistency | 20 | grouped slug-root sum diverges >5% |
| Obscure market | 10 | $10-50k liq, 24h vol > $1k |
| Fee-free geopolitical | 5 | category bonus |
| **Threshold** | **≥ 60** | Pass to Layer 3 |

### Layer 3 — Edge estimation (Perplexity-gated)
```bash
python3 .claude/skills/polymarket-bet/scripts/estimate_probability.py
```
- Only candidates with confluence_score ≥ 60
- 24h research cache (`data/memory/pm_research_cache.json`) — most cycles hit cache
- Hard cap: `PM_MAX_LLM_CALLS=10` per cycle (env-tunable)
- Forces NO_BET on insider-suspect categories (DOJ legal risk)
- Confidence-band shrinkage toward market price when band > 20%
- → `pm_estimates.json`

### Layer 4 — Risk gate (zero LLM)
```bash
python3 .claude/skills/polymarket-bet/scripts/risk_gate_pm.py
```
All checks must PASS:
1. `kelly_for_polymarket` returns BET (≥5% edge from `risk_params.json`)
2. Sized bet ≤ `max_bet_pct_bankroll` (5%)
3. Per-category exposure ≤ `max_exposure_per_category_pct` (15%)
4. Total PM exposure ≤ `max_total_exposure_pct` (40%)
5. ≤ `max_correlated_bets` (3) per (category, outcome) bucket
6. ≥ `diversification.min_categories` (3) once 2+ open
7. Liquidity ≥ `min_market_liquidity_usd` ($10k)
8. `system_state.trading_halted` ≠ `true`
9. No duplicate market position
- → `pm_approved_bets.json`

### Layer 5 — Execution
```bash
python3 .claude/skills/polymarket-bet/scripts/execute_bet.py             # paper (default)
python3 .claude/skills/polymarket-bet/scripts/execute_bet.py --live      # ignored unless PM_LIVE_TRADING=true
```
- **Paper mode (default):** writes to `trades` + `polymarket_bets` with `broker='paper'`, sends Telegram alert, mirrors to `memory/POLYMARKET-LOG.md`
- **Live mode:** stub for now — Phase 2 wires py-clob-client signing
- Idempotent: dedupes on (market_id, today)

## Config

- `config/risk_params.json::polymarket` — risk limits (single source of truth)
- `config/polymarket_accounts.json` — `tracked_accounts`, `wallet_clusters`, scoring weights
- `data/memory/pm_research_cache.json` — Perplexity TTL cache
- `data/memory/pm_wallet_state.json` — per-wallet last-poll timestamps

## Token discipline

- ~99% of cycles: 0 LLM calls (Layers 1, 2, 4, 5)
- Layer 3 hits cache before any HTTP cost
- Hard cap on per-cycle LLM calls
- Steady-state cost: < $1/day Perplexity, $0 Opus

## Phasing

- **Phase 1 (now):** Layers 1-2 stand-alone — verify wallet discovery + signal engine output
- **Phase 2 (after 30 paper bets, Brier < 0.20):** flip `PM_LIVE_TRADING=true`, wire py-clob-client signing in `execute_bet._live_place_order`
- **Phase 3:** auto-execute live (manual approval gate via Telegram for first 10 live bets)

## Verification

```bash
# Full pipeline (manual)
cd /Users/lazarstumbov/Documents/Business/Trading
python3 .claude/skills/polymarket-bet/scripts/discover_markets.py
python3 .claude/skills/polymarket-bet/scripts/discover_wallets.py
python3 .claude/skills/polymarket-bet/scripts/track_wallet_activity.py
python3 .claude/skills/polymarket-bet/scripts/signal_engine.py
python3 .claude/skills/polymarket-bet/scripts/estimate_probability.py
python3 .claude/skills/polymarket-bet/scripts/risk_gate_pm.py
python3 .claude/skills/polymarket-bet/scripts/execute_bet.py

# Inspect artifacts
ls data/signals/$(date -u +%F)/pm_*.json
sqlite3 data/db/trading.db "SELECT t.id, t.asset, t.direction, pb.edge_pct, t.broker FROM trades t JOIN polymarket_bets pb ON pb.trade_id=t.id ORDER BY t.id DESC LIMIT 5;"
tail -50 memory/POLYMARKET-LOG.md
```
