-- migrations/2026-05-15_cancel_stale_pm_bets.sql
-- One-shot: cancel the 7 still-open Polymarket bets that pre-date Stage-1
-- safeguards. All carry discovery_method='heuristic_paper', no wallet
-- evidence, and would not pass the current PM specialist veto.
--
-- Status='cancelled' (not 'closed') is the semantically honest mark — these
-- bets were never genuinely traded with informed signals; they are annulled.
-- pnl_usd=0 because no real money moved.
--
-- Idempotent: WHERE status='open' AND discovery_method='heuristic_paper'.
-- Re-runs are no-ops.
--
-- Apply with:
--   sqlite3 data/db/trading.db < migrations/2026-05-15_cancel_stale_pm_bets.sql
-- Verify:
--   sqlite3 data/db/trading.db "SELECT id, status, pnl_usd, closed_at FROM trades WHERE pillar='polymarket' AND id IN (6,7,8,9,10,12,13);"

BEGIN TRANSACTION;

UPDATE trades
   SET status     = 'cancelled',
       pnl_usd    = 0,
       pnl_pct    = 0,
       exit_price = entry_price,
       closed_at  = datetime('now'),
       reasoning  = COALESCE(reasoning, '{}') || ' [cancelled 2026-05-15: pre-Stage-1 heuristic_paper bet, no wallet evidence; retired for safeguard alignment]'
 WHERE pillar     = 'polymarket'
   AND status     = 'open'
   AND id        IN (
       SELECT t.id
         FROM trades t
         JOIN polymarket_bets pb ON pb.trade_id = t.id
        WHERE pb.discovery_method = 'heuristic_paper'
       );

COMMIT;

-- Summary check (informational; no transaction):
SELECT status, COUNT(*) AS n
  FROM trades
 WHERE pillar = 'polymarket'
 GROUP BY status;
