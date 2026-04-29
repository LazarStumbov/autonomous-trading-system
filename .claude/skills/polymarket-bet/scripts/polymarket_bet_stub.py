"""Stage 3 stub — full Polymarket pillar is deferred.

Modal's polymarket_scan cron calls this so nothing crashes. It emits a
structured "deferred" record to data/signals/<date>/polymarket_stub.json and
exits 0. When Pillar 2 ships (Stage 3), this stub is replaced by the real
CLOB integration: odds scraper → probability estimator → edge calculator →
Kelly-sized bet builder → risk gate → order placement.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "polymarket",
        "status": "deferred_stage_3",
        "message": "Polymarket pillar not yet implemented — no bets will be placed.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(out_dir / "polymarket_stub.json", "w") as f:
        json.dump(payload, f, indent=2)
    print("[polymarket_bet_stub] Stage 3 deferred — skipping Polymarket scan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
