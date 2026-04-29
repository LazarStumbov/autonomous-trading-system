"""Daily Perplexity research run.

Writes a dated research block to:
  * memory/RESEARCH-LOG.md (human-readable, committed to git)
  * data/signals/YYYY-MM-DD/research_log.json (machine-readable, consumed by
    opus_daily_review and the confluence_engine's macro-context features)

Six queries by default, all crypto-first but aware of macro:

  1. BTC dominance + on-chain flow
  2. Funding rates + open interest across top perps
  3. Next-24h macro catalysts (CPI, FOMC, NFP, geopolitical)
  4. Altcoin breadth / sector leaders last 24h
  5. Dominant market narrative (what are traders talking about)
  6. Equities / bonds / DXY snapshot (for the multi-asset expansion)

Each query is independent — one failing does NOT abort the run. If Perplexity
is not configured at all, the script writes an empty record so the downstream
Opus brief can still run.

Idempotency: re-running on the same day overwrites the JSON but APPENDS a new
section to the markdown. The markdown is append-only by design (audit trail).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.markdown_memory import append_research_log
from lib.perplexity import ask_safe, format_answer_with_citations, PerplexityNotConfigured


# Ordered: title → question. Keep under ~6 queries to control cost / latency.
RESEARCH_TOPICS: list[tuple[str, str]] = [
    (
        "BTC dominance & on-chain flow",
        "What is Bitcoin dominance right now, how has it moved in the last 24 hours, "
        "and are there any notable on-chain flows (large wallet moves, exchange "
        "inflows/outflows)? Cite sources.",
    ),
    (
        "Funding rates & open interest",
        "Give current perpetual futures funding rates and open interest trends for "
        "BTC, ETH, and the top 5 altcoin perps on Bybit and Binance in the last 24 "
        "hours. Flag anything extreme.",
    ),
    (
        "Macro catalysts next 24h",
        "What macro events (CPI, FOMC, NFP, central bank speakers, geopolitical "
        "flashpoints) are scheduled in the next 24 hours that could move crypto or "
        "US equity markets? Include exact times in UTC.",
    ),
    (
        "Altcoin breadth & sector leaders",
        "Which crypto sectors (L1, L2, DeFi, memes, AI, DePIN) are leading and "
        "lagging in the last 24 hours? Which individual tokens outperformed +15% "
        "and which underperformed -15%?",
    ),
    (
        "Dominant narrative",
        "What is the dominant narrative in crypto trading right now? What are the "
        "top posts on Crypto Twitter and in the larger crypto media saying today?",
    ),
    (
        "Equities / bonds / DXY snapshot",
        "Give a brief snapshot of US equities (SPY/QQQ), US 10-year yield, and DXY "
        "now vs 24 hours ago. Anything notable for a crypto trader to be aware of?",
    ),
]


SYSTEM_PROMPT = (
    "You are a market research assistant for an aggressive crypto day-trading bot. "
    "Reply in tight, factual markdown. No fluff. Quantify everything you can. "
    "Cite sources with URLs when available. Keep each answer under 200 words."
)


def run() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    md_blocks: dict[str, str] = {}

    for title, question in RESEARCH_TOPICS:
        r = ask_safe(question, system=SYSTEM_PROMPT)
        if r is None:
            md_blocks[title] = "_(skipped — Perplexity unavailable)_"
            results[title] = {"answer": None, "citations": [], "skipped": True}
        else:
            md_blocks[title] = format_answer_with_citations(r)
            results[title] = {
                "answer": r["answer"],
                "citations": r.get("citations", []),
                "model": r.get("model"),
            }

    record = {
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topics": results,
    }
    with open(out_dir / "research_log.json", "w") as f:
        json.dump(record, f, indent=2)

    # Append a section to RESEARCH-LOG.md
    append_research_log(md_blocks, date=today)

    ok = sum(1 for t in results.values() if not t.get("skipped"))
    print(f"[research_log] {ok}/{len(RESEARCH_TOPICS)} topics researched → {out_dir / 'research_log.json'}")
    return record


def main() -> int:
    try:
        run()
        return 0
    except PerplexityNotConfigured as e:
        # Still want a stub file so the downstream Opus brief can run.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "research_log.json", "w") as f:
            json.dump(
                {
                    "date": today,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "topics": {},
                    "error": str(e),
                },
                f,
                indent=2,
            )
        print(f"[research_log] perplexity unconfigured — wrote empty stub")
        return 0


if __name__ == "__main__":
    sys.exit(main())
