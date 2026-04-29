"""Anthropic Message Batches helper — 50% discount, 24h SLA.

Use for latency-tolerant work: weekly report (submit Sat night, pull Sun
morning), hypothesis generation (never urgent), back-fill sentiment scoring
across a week of news. NEVER use for the daily brief or trade post-mortems —
those need synchronous responses.

Pattern:
    1. submit_batch([requests]) -> batch_id
    2. wait_for_batch(batch_id)      # polls every N minutes
    3. fetch_results(batch_id)       # returns list of (custom_id, response)
"""

from __future__ import annotations

import os
import time
from typing import Iterable, Optional

try:
    import anthropic
except ImportError:  # pragma: no cover - optional dependency at import time
    anthropic = None  # type: ignore


def _client() -> "anthropic.Anthropic":  # type: ignore
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed; run `pip install anthropic`.")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is empty; cannot submit batch.")
    return anthropic.Anthropic(api_key=api_key)


def submit_batch(requests: Iterable[dict]) -> str:
    """Submit a list of message-creation requests as a batch.

    Each request must be a dict with keys: `custom_id`, `params` (where
    `params` is the same dict you'd pass to `client.messages.create(...)`).
    Returns the batch_id.
    """
    client = _client()
    payload = []
    for r in requests:
        if "custom_id" not in r or "params" not in r:
            raise ValueError("each request needs custom_id + params")
        payload.append({"custom_id": r["custom_id"], "params": r["params"]})
    resp = client.messages.batches.create(requests=payload)
    return resp.id


def get_batch(batch_id: str) -> dict:
    client = _client()
    return client.messages.batches.retrieve(batch_id).model_dump()


def wait_for_batch(batch_id: str, poll_seconds: int = 600, timeout_seconds: int = 86400) -> dict:
    """Block (poll) until batch status is `ended`, or timeout."""
    started = time.time()
    while True:
        b = get_batch(batch_id)
        if b.get("processing_status") in ("ended",):
            return b
        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"batch {batch_id} did not complete in {timeout_seconds}s")
        time.sleep(poll_seconds)


def fetch_results(batch_id: str) -> list[dict]:
    """Stream batch results. Each row: {custom_id, result, error}."""
    client = _client()
    out: list[dict] = []
    for entry in client.messages.batches.results(batch_id):
        # entry has .custom_id and .result (success/errored)
        d = entry.model_dump() if hasattr(entry, "model_dump") else dict(entry)
        out.append(d)
    return out
