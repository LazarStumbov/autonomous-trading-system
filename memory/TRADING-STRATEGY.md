# Trading Strategy — Doctrine

> Static reference. Evolves only via explicit human decision, never by auto-tune.

## Identity

- **Capital:** $100–$500 starting bankroll
- **Timeframes:** aggressive. Primary 5m / 15m / 1h / 4h. No "multi-week swing" trades.
- **Pillars:**
  - **Pillar 1 — Market trading (Bybit):** crypto perps + spot; expanding to stocks / bonds / CFDs (Stage 4 multi-asset).
  - **Pillar 2 — Polymarket (deferred Stage 3):** prediction-market edge detection, quarter-Kelly sizing.
- **Goal:** grow capital aggressively while refusing to break the hardcoded risk rules below.

## Absolute risk rules (hardcoded, never auto-tuned)

1. Max **2%** of capital risked per single trade.
2. Max **6%** total daily drawdown → HALT for the day.
3. Max **15%** weekly drawdown → HALT until manual review.
4. Every position MUST have a stop loss. Default `2×ATR`. Max stop distance 5%.
5. Default leverage 3x, max 10x — only on confluence ≥ 80.
6. Max **30%** of capital deployed simultaneously.
7. Max 3 correlated positions in the same direction.
8. Min 2:1 risk-reward ratio.
9. Circuit breaker: 3 consecutive losses → halt 4 hours.
10. Polymarket max 5% bankroll per bet, quarter-Kelly, min 5% edge.

## Strategy sourcing

Strategies are loaded from `lib/strategy_library/` and registered in
`config/strategy_registry.json`. Every strategy inherits from
`lib.strategy_engine.Strategy` and declares `safe_bounds` for any tunable
parameter. The self-improvement loop can only tune within those bounds.

## Lifecycle gate

```
disabled → backtest → paper → live → (demote) paper / disabled
```

Promotion / demotion thresholds live in `config/strategy_gates.json`. No
strategy goes live without passing backtest gates, then 14 paper-trading days.

## Confluence

Every setup is scored 0–100 by combining:
- technical indicators,
- news signals,
- trader copy signals,
- TradingView alerts,
- strategy library consensus.

Minimum score to enter: **60**. Above **80** unlocks higher leverage (up to
10x), but all other risk rules still apply.

## Decision cadence

- 15m — news scan.
- 1h — market scan + confluence.
- 4h — Polymarket (when live).
- Daily 08:00 UTC — Opus 4.7 daily market brief.
- Daily 21:00 UTC — performance report + self-improve post-mortems + trade review packets.
- Weekly Sun 12:00 UTC — weekly review with letter grade A–F.

## What we will NOT do

- Revenge trading (circuit breaker enforced).
- "All-in" bets. Risk-per-trade is capped regardless of confluence.
- Manual parameter edits on live strategies without going back to backtest first.
- Trade assets outside our broker adapter allow-list.
