# Paper Trading Runbook

**Status:** PAPER_MODE active. 65 strategies promoted. Virtual balance $500.

## What's running

When the bot is deployed to Modal (cron jobs firing on schedule), every cycle:

1. **Every 15 min** — `news_scan`: scans Finnhub for breaking news, scores urgency
2. **Every 1 hour** — `market_scan`: pulls live OKX prices, runs all 65 strategies
   through screener → confluence → risk gate. PASSed setups are simulated as
   paper trades against the live public price.
3. **Continuously** (in `market_scan`) — `position_monitor`: checks open paper
   trades against live prices, closes on SL/TP hit, credits virtual balance.
4. **06:00 UTC daily** — `opus_daily_brief`: Opus 4.7 writes
   `memory/DAILY-BRIEF.md` summarizing overnight signals + open positions
5. **21:00 UTC daily** — `daily_report`: PDF + Telegram summary of day's P&L
6. **12:00 UTC Sunday** — `weekly_review`: Opus narrative + grade A–F,
   strategy promotion gate runs

## Toggling paper ↔ live

Paper mode is controlled by `PAPER_MODE=true` in `.env` (and Modal's
`trading-broker-keys` secret).

- **Stay in paper:** keep `PAPER_MODE=true`. Bot runs against live prices,
  no real money. Trades tagged `broker='paper'` in DB.
- **Switch to live OKX demo:** set `PAPER_MODE=false`, paste OKX_API_KEY +
  OKX_SECRET_KEY + OKX_PASSPHRASE (with `OKX_DEMO=true`). Same code path,
  trades go to OKX paper account, tagged `broker='okx_demo'`.
- **Switch to real money:** set `OKX_DEMO=false`. **Only after** 14-day
  paper window completes and you've reviewed performance manually.

## Daily checks while away

The bot runs autonomously. When you check in, you can review:

- `python3 dashboard/app.py` then `http://127.0.0.1:8765` — local dashboard
  with trades, P&L, equity curve
- `memory/DAILY-BRIEF.md` — Opus-written morning briefing
- `memory/WEEKLY-REVIEW.md` — Sunday's Opus narrative + grade
- Telegram — daily summary lands at 21:00 UTC
- `reviews/pending/` — trade review packets accumulating for your
  manual-paste session

## Safety rails active in paper mode

All 10 hardcoded risk rules are enforced:
- Max 2% capital per trade ($10 on $500)
- Max 6% daily drawdown → halt trading
- Max 15% weekly drawdown → halt + manual review
- Every position has SL (max 5% distance)
- Leverage 3x default, 10x cap on confluence ≥80
- Max 30% capital deployed simultaneously
- Max 3 correlated positions
- Min 2:1 risk-reward
- 3 consecutive losses → 4-hour cooldown
- Category cooldown after 2 consecutive losses on same asset class

## When you return

1. Read `memory/WEEKLY-REVIEW.md` — Opus's grade and narrative
2. Open `dashboard/app.py` — visualize what happened
3. Skim `reviews/pending/` — paste each into Claude UI, get verdict, drop
   into `reviews/completed/`. Ingester promotes/kills hypotheses next cron
4. Compare paper P&L against TV severity backtest expectations — strategies
   wildly off should be investigated
5. Decide what (if anything) to promote from `mode=paper` → `mode=live`
