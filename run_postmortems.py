"""
Batch post-mortem runner: sends each pending trade review packet to claude-opus-4-7
and saves the response to reviews/completed/<same_filename>.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import anthropic

PROJECT_ROOT = Path("/Users/lazarstumbov/Documents/Business/Trading")
PENDING_DIR = PROJECT_ROOT / "reviews" / "pending"
COMPLETED_DIR = PROJECT_ROOT / "reviews" / "completed"

# Load API key from .env
def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env(PROJECT_ROOT / ".env")

SYSTEM_PROMPT = (
    "You are a professional quant trader performing post-trade analysis. "
    "Be concise, analytical, and honest. Focus on process quality, not just outcomes. "
    "Always end with the required JSON block."
)

MODEL = "claude-opus-4-7"
MAX_TOKENS = 1500
BATCH_SIZE = 5
SLEEP_BETWEEN_BATCHES = 2  # seconds


def get_pending_files() -> list[Path]:
    return sorted(PENDING_DIR.glob("*.md"))


def already_completed(filename: str) -> bool:
    return (COMPLETED_DIR / filename).exists()


def call_api(client: anthropic.Anthropic, packet_text: str) -> str:
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": packet_text}],
    )
    return message.content[0].text


def main() -> None:
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    pending = get_pending_files()
    to_process = [p for p in pending if not already_completed(p.name)]
    skipped = len(pending) - len(to_process)

    print(f"Found {len(pending)} pending packets, {skipped} already completed, {len(to_process)} to process.")

    processed = 0
    errors = 0

    for batch_start in range(0, len(to_process), BATCH_SIZE):
        batch = to_process[batch_start : batch_start + BATCH_SIZE]
        print(f"\n--- Batch {batch_start // BATCH_SIZE + 1} ({len(batch)} files) ---")

        for packet_path in batch:
            print(f"  Processing {packet_path.name} ...", end=" ", flush=True)
            try:
                packet_text = packet_path.read_text()
                response_text = call_api(client, packet_text)
                out_path = COMPLETED_DIR / packet_path.name
                out_path.write_text(response_text)
                print("OK")
                processed += 1
            except Exception as e:
                print(f"ERROR: {e}")
                errors += 1

        # Sleep between batches (but not after the last one)
        if batch_start + BATCH_SIZE < len(to_process):
            print(f"  Sleeping {SLEEP_BETWEEN_BATCHES}s between batches...")
            time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"\nDone. Processed: {processed}, Errors: {errors}, Skipped (already done): {skipped}")


if __name__ == "__main__":
    main()
