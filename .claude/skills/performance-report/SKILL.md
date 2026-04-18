---
name: performance-report
description: Generate daily and weekly performance reports. Track P&L, calculate Sharpe/Sortino/win rate, create professional PDF reports, and send summaries via Telegram.
allowed-tools: Bash, Read
---

# Performance Report Skill

Track everything. Measure everything. Report everything.

## When to Use
- Daily at 21:00 UTC (after market close equivalent)
- Weekly on Sunday 12:00 UTC
- Via `/weekly-review` for manual review

## Pipeline

### Daily Report

#### Step 1: Trade Journal Update
```bash
python3 .claude/skills/performance-report/scripts/trade_journal.py --date today
```
Ensures all trades from today are properly logged with complete data.

#### Step 2: P&L Calculation
```bash
python3 .claude/skills/performance-report/scripts/pnl_calculator.py --date today
```
Calculates realized + unrealized P&L for the day. Updates `daily_pnl` table.

#### Step 3: Performance Metrics
```bash
python3 .claude/skills/performance-report/scripts/performance_metrics.py --period daily
```
Calculates: win rate, avg win/loss, profit factor, expectancy.

#### Step 4: Generate PDF
```bash
python3 .claude/skills/performance-report/scripts/generate_daily_report.py
```
Creates professional PDF using `lib/pdf_generator.py`. Saves to `data/reports/daily/`.

### Weekly Report

#### Step 1-3: Same as daily but for the week

#### Step 4: Advanced Metrics
```bash
python3 .claude/skills/performance-report/scripts/performance_metrics.py --period weekly
```
Additionally calculates:
- Sharpe ratio
- Sortino ratio
- Max drawdown
- Strategy-level breakdown
- Followed accounts performance attribution
- Polymarket bet success rate

#### Step 5: Generate Weekly PDF
```bash
python3 .claude/skills/performance-report/scripts/generate_weekly_report.py
```
Comprehensive weekly report with all metrics, strategy breakdown, and recommendations.

## Report Contents
### Daily
- Date, starting/ending capital
- Total P&L (realized + unrealized)
- Trade list with individual P&L
- Win/loss count and rate
- Max drawdown for the day
- Pillar breakdown (market vs polymarket)

### Weekly
- All daily metrics aggregated
- Sharpe ratio, Sortino ratio
- Profit factor, expectancy
- Strategy performance comparison
- Top/bottom performers
- Followed accounts attribution
- Recommendations for parameter adjustments
