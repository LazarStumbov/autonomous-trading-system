"""Trade journal RAG (Workstream 6 — Stage 6, no embeddings yet).

Stage 6 ships keyword + structured-query retrieval over `trades` +
`trade_journal` + `agent_memory_semantic`. Vector embeddings (voyage-3-lite
or text-embedding-3-small via sqlite-vss) land in Stage 7 alongside the
RAG-over-research-log work.

The point is: the daily synth agent can ask "show closed trades within 24h
of an FOMC release" and get retrieval rather than a full table scan, so it
can ground its lessons in actual past behavior rather than training-set memory.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection  # noqa: E402


def search_trades(
    *,
    keywords: list[str] | None = None,
    strategy: str | None = None,
    pillar: str | None = None,
    asset_substr: str | None = None,
    days: int = 90,
    only_closed: bool = True,
    only_winners: bool = False,
    only_losers: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Keyword + structured filter over trades.

    `keywords` matches against trades.reasoning JSON (case-insensitive LIKE).
    Useful for queries like "find trades that mentioned 'flash crash' or
    'FOMC' in their reasoning".
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = "SELECT * FROM trades WHERE COALESCE(closed_at, timestamp) >= ?"
    params: list = [cutoff]
    if only_closed:
        q += " AND status = 'closed'"
    if only_winners:
        q += " AND pnl_usd > 0"
    if only_losers:
        q += " AND pnl_usd < 0"
    if strategy:
        q += " AND strategy = ?"
        params.append(strategy)
    if pillar:
        q += " AND pillar = ?"
        params.append(pillar)
    if asset_substr:
        q += " AND LOWER(asset) LIKE ?"
        params.append(f"%{asset_substr.lower()}%")
    if keywords:
        for kw in keywords:
            q += " AND LOWER(COALESCE(reasoning, '')) LIKE ?"
            params.append(f"%{kw.lower()}%")
    q += " ORDER BY COALESCE(closed_at, timestamp) DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_memory(
    *,
    keywords: list[str] | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search agent_memory_semantic for lessons + rules matching keywords."""
    q = "SELECT * FROM agent_memory_semantic WHERE superseded_by IS NULL"
    params: list = []
    if category:
        q += " AND category = ?"
        params.append(category)
    if keywords:
        for kw in keywords:
            q += " AND (LOWER(body) LIKE ? OR LOWER(COALESCE(subject,'')) LIKE ?)"
            params.append(f"%{kw.lower()}%")
            params.append(f"%{kw.lower()}%")
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    conn = get_connection()
    try:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def context_for_agent(
    *,
    asset: str | None = None,
    strategy: str | None = None,
    keywords: list[str] | None = None,
    days: int = 30,
    max_trades: int = 10,
    max_lessons: int = 10,
) -> dict:
    """Bundle relevant retrieval for a single agent call.

    Returns: {trades, lessons, win_rate, avg_pnl} keyed to the agent's question.
    """
    trades = search_trades(
        keywords=keywords,
        strategy=strategy,
        asset_substr=asset,
        days=days,
        only_closed=True,
        limit=max_trades,
    )
    lessons = search_memory(keywords=keywords, limit=max_lessons)
    wins = sum(1 for t in trades if (t.get("pnl_usd") or 0) > 0)
    avg_pnl = (sum((t.get("pnl_usd") or 0) for t in trades) / len(trades)) if trades else 0
    return {
        "trades": trades,
        "lessons": lessons,
        "stats": {
            "count": len(trades),
            "win_rate": (wins / len(trades)) if trades else None,
            "avg_pnl_usd": round(avg_pnl, 2),
        },
    }


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser()
    p.add_argument("--keywords", nargs="*")
    p.add_argument("--strategy")
    p.add_argument("--asset")
    p.add_argument("--days", type=int, default=30)
    args = p.parse_args()
    out = context_for_agent(
        keywords=args.keywords, strategy=args.strategy, asset=args.asset, days=args.days
    )
    print(json.dumps(out, indent=2, default=str))
