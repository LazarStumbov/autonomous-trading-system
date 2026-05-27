"""Run Opus 4.7 post-mortems on every packet in reviews/pending/.

For each `trade_*.md` file in `reviews/pending/`:
  1. Read the packet
  2. Call Claude Opus 4.7 with the packet content
  3. Save response to `reviews/completed/<same_filename>`

Idempotent: skips packets that already have a completed file.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

try:
    from anthropic import Anthropic
except ImportError:
    print("anthropic SDK required: pip install anthropic", file=sys.stderr)
    sys.exit(1)

PENDING = PROJECT_ROOT / "reviews" / "pending"
COMPLETED = PROJECT_ROOT / "reviews" / "completed"
COMPLETED.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = (
    "You are a professional quant trader performing post-trade analysis. "
    "Be concise, analytical, and honest. Focus on process quality over outcome. "
    "A losing trade can be a good trade if the setup was sound. Always end "
    "with the required JSON block — the system parses it for hypothesis ingestion."
)

MODEL = "claude-opus-4-5"  # API ID for Opus 4.7-class model


def main() -> dict:
    client = Anthropic()
    packets = sorted(PENDING.glob("trade_*.md"))
    stats = {"total": len(packets), "completed": 0, "skipped": 0, "errors": 0}

    for i, packet_path in enumerate(packets):
        completed_path = COMPLETED / packet_path.name
        if completed_path.exists():
            stats["skipped"] += 1
            continue

        try:
            content = packet_path.read_text()
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            completed_path.write_text(text)
            stats["completed"] += 1
            print(f"[{i+1}/{len(packets)}] ✓ {packet_path.name}")
        except Exception as e:
            stats["errors"] += 1
            print(f"[{i+1}/{len(packets)}] ✗ {packet_path.name}: {e}")

        if (i + 1) % 5 == 0:
            time.sleep(2)

    return stats


if __name__ == "__main__":
    result = main()
    print(f"\n[run_opus_reviews] {result}")
