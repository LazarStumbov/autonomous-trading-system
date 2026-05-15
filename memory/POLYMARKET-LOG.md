# Polymarket Log

## 2026-05-15 — Stale-bet cleanup

Cancelled 7 still-open PM bets (trade ids 6, 7, 8, 9, 10, 12, 13). All carried
`discovery_method='heuristic_paper'`, all were placed before the Stage-1
safeguards landed (extreme-tail veto on `<0.05` or `>0.95` market price absent
wallet evidence, confluence-≥80-or-evidence gate, brain specialist rule check).
None would survive the current PM pipeline if re-evaluated today.

Status moved `open → cancelled` with pnl_usd=0 and exit_price=entry_price. They
are annulled, not closed-with-loss — the system did not have informed signals
when it placed them, so calling these "losses" would corrupt the training
distribution.

Migration: `migrations/2026-05-15_cancel_stale_pm_bets.sql` (idempotent on
status='open' + discovery_method='heuristic_paper').

Forward: every new PM bet must clear `brain_pm_sanity_check` (deterministic
fallback covers rules 1–3 even with no Anthropic key). `tracked_accounts` is
still empty in `config/polymarket_accounts.json`; the PM hot-path guard in
`modal/trading_webhook.py::_pm_guard_ok` short-circuits the pipeline until
`discover_wallets.py` (Sunday weekly cron) produces a populated wallet list.

---

## Bet #6 · YES · Will the Detroit Pistons win the NBA Eastern Conference Finals?  ·  2026-05-11 12:44 UTC

- **Mode:** paper
- **Side:** YES @ 0.280
- **Estimated probability:** 0.45
- **Edge:** 17.0%
- **Size:** $12.50
- **Category:** will-the-detroit-pistons-win-the-nba-eastern-conference-finals
- **Confluence:** 30
- **Trade ID:** 6

**Key factors:**
- Strong home record
- Opponent fatigue
- Historical playoff form

## Bet #7 · YES · Will Abelardo de la Espriella  win the 2026 Colombian presidential election?  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.425
- **Estimated probability:** 0.445
- **Edge:** 2.0%
- **Size:** $2.17
- **Category:** colombia-presidential-election
- **Confluence:** 30
- **Trade ID:** 7

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #8 · YES · Will the San Antonio Spurs win the NBA Western Conference Finals?  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.262
- **Estimated probability:** 0.2815
- **Edge:** 2.0%
- **Size:** $1.70
- **Category:** nba-playoffs-western-conference-champion
- **Confluence:** 30
- **Trade ID:** 8

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #9 · YES · Will Abelardo de la Espriella win the 1st round of the 2026 Colombian presidenti  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.123
- **Estimated probability:** 0.1435
- **Edge:** 2.0%
- **Size:** $1.42
- **Category:** colombia-presidential-election-1st-round-winner
- **Confluence:** 30
- **Trade ID:** 9

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #10 · YES · Will Paloma Valencia win the 2026 Colombian presidential election?  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.158
- **Estimated probability:** 0.1775
- **Edge:** 2.0%
- **Size:** $1.47
- **Category:** will-paloma-valencia-win-the-2026-colombian-presidential-election
- **Confluence:** 30
- **Trade ID:** 10

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #11 · YES · Will Aston Villa finish in 3rd place in the 2025-26 English Premier League?  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.002
- **Estimated probability:** 0.0215
- **Edge:** 2.0%
- **Size:** $1.25
- **Category:** english premier league – 3rd place 
- **Confluence:** 30
- **Trade ID:** 11

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #12 · YES · Will Paloma Valencia win the 1st round of the 2026 Colombian presidential electi  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.009
- **Estimated probability:** 0.0295
- **Edge:** 2.0%
- **Size:** $1.25
- **Category:** will-paloma-valencia-win-the-1st-round-of-the-2026-colombian-presidential-election
- **Confluence:** 30
- **Trade ID:** 12

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes

## Bet #13 · YES · Will Bitcoin hit $150k by June 30, 2026?  ·  2026-05-12 06:01 UTC

- **Mode:** paper
- **Side:** YES @ 0.013
- **Estimated probability:** 0.0335
- **Edge:** 2.0%
- **Size:** $1.28
- **Category:** when-will-bitcoin-hit-150k
- **Confluence:** 30
- **Trade ID:** 13

**Key factors:**
- paper heuristic from confluence=30, smart-money=yes
