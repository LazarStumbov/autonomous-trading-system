# Day-Trading Playbook

> Distilled from Brooks, Grimes, Douglas, CryptoCred, Hougaard, ICT (filtered),
> Stockbee, and the PineCoders best-practice library. Used as system-prompt
> context for the Opus daily brief and the hypothesis generator. Updated as new
> patterns earn or lose their place.

---

## 1. Setup taxonomy

Every actionable setup lives in one of six buckets. Knowing which bucket a chart
is in tells you which tools to use and what mistakes to avoid.

### 1.1 Trend continuation
- **Definition:** higher-highs and higher-lows (or the inverse) on the trade
  timeframe; pullback into a moving average / prior structure / Fibonacci zone;
  resumption signal in trend direction.
- **Best in:** crypto perp 1h/4h, equities post-open trend day.
- **Brooks lens:** "with-trend bars" expand, "counter-trend bars" stall.
- **Stockbee lens:** episodic pivot — three weeks tight, then expansion.
- **Trap:** entering after the third or fourth pullback (over-extended).

### 1.2 Range / fade
- **Definition:** clear horizontal upper/lower bounds; price oscillates with no
  expansion; volume decays.
- **Best in:** Asia session crypto, post-earnings drift days.
- **CryptoCred lens:** mark range high / range low / mid; trade rejections, not
  extensions.
- **Trap:** fading the range during a regime shift — the failed-fade is one of
  the highest-conviction breakout signals.

### 1.3 Breakout
- **Definition:** price escapes a multi-bar range or major level on volume.
- **Best in:** session opens, news-catalyst windows.
- **Stockbee lens:** 4% breakout on 50%+ above-average volume.
- **PineCoders lens:** confirm with squeeze release (BB inside KC → BB outside).
- **Trap:** chasing — the cleanest breakouts retest the level within 1–3 bars.

### 1.4 Failed breakout / fade
- **Definition:** price breaks a level then reclaims it within 1–3 bars on
  declining volume.
- **Best in:** post-pump crypto, opex weeks in equities.
- **ICT lens (filtered):** "swing failure pattern" / "liquidity sweep" — stops
  taken above prior high, then sharp reversal.
- **Trap:** confusing a fast retest with a true failure. Wait for a second
  confirmation candle before entering the fade.

### 1.5 News catalyst
- **Definition:** scheduled or breaking news (CPI, FOMC, ETF approval, exploit,
  hack) materially repricing the asset.
- **Best in:** the first 5–30 minutes after the print.
- **Hougaard lens:** size up *only* when the news cleanly aligns trend +
  catalyst + level. Otherwise, smaller than usual — volatility shreds tight
  stops.
- **Trap:** trading the first wick. Wait for the first 5-min closing candle
  after the print before committing.

### 1.6 Gap (equities only)
- **Definition:** opening price > or < prior day's high/low by ≥0.5%.
- **Best in:** US equity open 9:30–10:00 ET.
- **Plays:** gap-and-go (continuation) vs. gap-fill (reversion). Gap+volume+
  RVOL >2 → continuation. Low-volume gap → fill.
- **Trap:** trading both directions in the first 5 minutes — pick a thesis
  before the open.

---

## 2. Entry triggers (3–5 per setup)

### Trend continuation
1. Pullback to 20/50 EMA + bullish engulfing close above the EMA.
2. Pullback to prior breakout level (now support) + RSI bounces from 40 zone.
3. Inside-bar break in trend direction (Brooks).
4. Higher-low formation on lower-timeframe + supertrend flip back to trend.
5. Volume contraction in pullback + first expansion candle.

### Range
1. Touch of range high / low + rejection wick + opposite-color follow-through.
2. RSI divergence at the band edge (price new extreme, RSI not).
3. VWAP reclaim from below (long fade of low).
4. Failed-break candle (poke + reclaim) at range edge.

### Breakout
1. Range high break with volume ≥1.5× 20-bar avg.
2. Donchian-20 break + ATR expansion ≥1.5× recent.
3. Squeeze release (Bollinger inside Keltner → Bollinger outside) in trend.
4. Retest of breakout level within 1–3 bars + bullish hammer.
5. Stop-run reversal: break above prior high, immediate reclaim — long with
   stop below the wick low.

### Failed breakout
1. New high → close back inside range within 1 bar + bearish engulfing.
2. Stop hunt above key level, then 5-min close back below.
3. Double-top rejection where second peak is on lower volume.
4. RSI bearish divergence on the higher high.

### News catalyst
1. First 5-min candle close in catalyst direction with above-avg volume.
2. Retest of pre-news consolidation top/bottom (now flipped) on lighter volume.
3. Confluence: pre-existing trend + catalyst aligns + clean level retest.

### Gap
1. Gap-and-go: ORB (opening-range breakout) of first 5-min bar.
2. Gap-fill fade: rejection at prior day's close + volume.
3. Gap with strong premarket volume + sector confirmation.

---

## 3. Stop placement rules

**Never enter without a defined stop.** This is hardcoded in `risk_engine.py` —
the playbook just guides where the stop *lives*.

| Setup | Stop placement |
|---|---|
| Trend continuation | 1× ATR below the pullback low (long) — invalidates the HL structure |
| Range | Beyond the range edge by 0.25× ATR — fade is wrong if level breaks cleanly |
| Breakout | Below the breakout candle's midpoint or below the retested level |
| Failed breakout | Above the failure wick high (long: above sweep low) |
| News catalyst | 1.5× ATR — wider than usual to absorb noise |
| Gap | Below the opening-range low (gap-and-go) or above the gap fill price (fade) |

**Hard cap (risk_engine):** stop distance ≤ 5% of entry. Tighter is better; if
you can't structure a stop within 5%, you don't have a setup, you have a hope.

---

## 4. Exit rules

**Three exits per trade — pick any two:**

1. **Target (TP):** R:R ≥2.0 minimum (risk_engine enforces). 2.5–3.0 is typical
   for trend continuation. Range trades take 1.5–2.0R because the level is the
   target.
2. **Trailing stop:** progressive trail tier engages once paper P&L > +3%; tier
   thereafter is `entry + 0.5 × (high - entry)` for longs. See
   `position_monitor.py` for the implementation.
3. **Time stop:** if the trade hasn't moved ±0.5R within N bars on the entry
   timeframe, exit. Setups that don't go are usually wrong, just slowly.

**Partial exits:**
- Take 50% off at 1R, move stop to break-even, let the rest ride to TP.
- For high-conviction setups (confluence ≥80) with strong trend, scale instead
  of full close — 30% / 30% / 40% at 1R / 2R / 3R.

---

## 5. What kills day-traders (Mark Douglas filter)

The bot doesn't have emotions, but every prompt and parameter that flows
through Opus must respect these failure modes — they show up as hypothesis
proposals that look good but historically blow up accounts.

1. **Over-trading after a loss.** Circuit breaker: 3 consecutive losses → halt
   for 4 hours. Category cooldown: 2 consecutive losses on a category → 4h
   cooldown for that category only.
2. **Moving stops away from price.** The system never widens stops post-entry.
   Trailing stops only tighten.
3. **Adding to a loser.** No averaging down. Period. New entries require new
   setups.
4. **Counter-trend in a strong trend.** Fade strategies are gated by HTF
   alignment — `confluence_detector.py` blocks counter-HTF fades when the 1h
   trend is strong.
5. **Sizing up after wins.** Position size is capital-relative, not streak-
   relative. Hot streaks are not a signal to lever up.
6. **Trading the news without a plan.** News catalysts only trigger when they
   align with a pre-existing technical level + trend (3-source confluence).
7. **Confusing volatility with edge.** Edge = positive expected value over
   ≥30 trades. Anything less is noise.

---

## 6. Per-source short bibliography

- **Al Brooks**, *Reading Price Charts Bar by Bar* (2009) and *Trading Price
  Action Trends / Reversals / Trading Ranges* (2012). Brooks Trading Course
  videos. *Why:* gold standard for pure price action; teaches reading any
  market with no indicators.
- **Adam Grimes**, *The Art and Science of Technical Analysis* (2012);
  adamhgrimes.com blog. *Why:* statistically-honest TA; counterweight to
  pattern voodoo; "the random walk is more random than you think."
- **Mark Douglas**, *Trading in the Zone* (2000), *The Disciplined Trader*
  (1990). *Why:* the failure-mode catalog.
- **CryptoCred** (free YouTube series, 2018–2021). *Why:* crypto-specific S/R,
  range trading, market structure. Free, rigorous, no paywall.
- **Tom Hougaard**, *Best Loser Wins* (2022). *Why:* aggressive sizing within
  defined risk; useful frame for the 2% / 10x ceiling.
- **ICT (Inner Circle Trader)** — selectively. Concepts kept: market structure,
  liquidity sweeps, order blocks, fair value gaps. Concepts ignored: cult
  language, "killzones" without statistical evidence, time-of-day mysticism.
- **Stockbee (Pradeep Bonde)** — momentum / episodic pivots / 4% breakouts.
  Codifiable, mechanical, well-suited to our screener.
- **PineCoders open library** (TradingView). *Why:* best-practice Pine Script;
  source for `tradingview/` strategy ports under MPL/MIT licenses only.

---

## 7. How this playbook is used

- **Opus daily brief** (cron 08:00 UTC): system prompt includes sections 1, 4,
  and 5 verbatim. Brief references the current TV multi-TF state.
- **Hypothesis generator** (weekly): prompt seeded with section 5 to filter
  out obviously-blow-up proposals.
- **`confluence_detector.py`**: setup taxonomy (section 1) maps onto the
  signal-type buckets the detector produces.
- **`screener.py`**: entry triggers (section 2) inform which strategy
  combinations are flagged HIGH_CONVICTION.
- **`position_monitor.py`**: exit rules (section 4) drive the trail tier
  schedule.

This file is updated when a new pattern earns or loses its place — both human
review (manual edits) and Opus weekly review can amend it via the
`memory_updater.py` script (no untraceable rewrites).
