"""Minimal Perplexity chat-completions wrapper.

Used by the news-monitor skill for citation-backed research. Perplexity is
the right tool here because its responses come with live web citations,
which matters when we feed the output into the Opus 4.7 daily brief or into
the markdown research log for later human audit.

Design notes:
  * No hard dep. If `PERPLEXITY_API_KEY` isn't set, calls raise a clear
    `PerplexityNotConfigured` so callers can fall back gracefully.
  * `requests` is already pulled in by `lib/notifier.py`, so no new deps.
  * Citations from Perplexity arrive in a `citations` field on the response;
    we preserve them and surface them to the caller.
  * Small defaults: `sonar` model is fast + cheap; callers can override.

Ref: Perplexity Chat Completions API (OpenAI-compatible schema).
"""

from __future__ import annotations

import os
from typing import Optional

import requests


class PerplexityNotConfigured(RuntimeError):
    pass


class PerplexityError(RuntimeError):
    pass


PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
DEFAULT_MODEL = os.environ.get("PERPLEXITY_MODEL", "sonar")
DEFAULT_TIMEOUT = 45


def _api_key() -> str:
    key = os.environ.get("PERPLEXITY_API_KEY")
    if not key:
        raise PerplexityNotConfigured(
            "PERPLEXITY_API_KEY is not set. Add it to .env or Modal secrets."
        )
    return key


def ask(
    question: str,
    *,
    system: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 700,
    temperature: float = 0.2,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """One-shot research query.

    Returns:
        {
          "answer": str,             # the textual answer
          "citations": list[str],    # URLs (empty if model didn't return any)
          "model": str,
          "raw": dict,               # full API response for inspection
        }

    Raises PerplexityNotConfigured if no API key, PerplexityError on HTTP failure.
    """
    key = _api_key()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(PERPLEXITY_URL, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise PerplexityError(f"Perplexity network error: {e}") from e

    if resp.status_code != 200:
        raise PerplexityError(
            f"Perplexity {resp.status_code}: {resp.text[:400]}"
        )

    data = resp.json()
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise PerplexityError(f"Unexpected Perplexity response shape: {e} · {data}") from e

    # Citations live at the top level on Sonar responses.
    citations = data.get("citations") or []
    return {
        "answer": answer,
        "citations": citations,
        "model": data.get("model", model),
        "raw": data,
    }


def ask_safe(question: str, **kwargs) -> Optional[dict]:
    """Like `ask()` but returns None on failure instead of raising.

    Use this when Perplexity is a nice-to-have and the caller should degrade
    rather than abort (e.g. daily research log where one topic can fail).
    """
    try:
        return ask(question, **kwargs)
    except (PerplexityNotConfigured, PerplexityError) as e:
        print(f"[perplexity] skipped: {e}")
        return None


def format_answer_with_citations(result: dict) -> str:
    """Render an answer dict as markdown with citations appended."""
    if not result:
        return "_(no answer)_"
    out = result["answer"].rstrip()
    cites = result.get("citations") or []
    if cites:
        out += "\n\n**Sources:**\n" + "\n".join(f"- {c}" for c in cites)
    return out


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "What is the current BTC spot price, roughly?"
    try:
        r = ask(q)
        print(format_answer_with_citations(r))
    except PerplexityNotConfigured as e:
        print(f"[perplexity] not configured: {e}")
        sys.exit(2)
