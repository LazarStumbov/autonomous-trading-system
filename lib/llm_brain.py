"""Central Anthropic SDK entry point for the multi-agent brain.

Every agent call in the system funnels through here so we get:
  - Single source of truth for model IDs and tiering
  - Prompt caching by default on system prompts (5min ephemeral cache)
  - Cost tracking via lib.anthropic_cost_tracker (already enforces monthly cap)
  - Schema validation on JSON outputs (via lib.agent_schemas)
  - Action logging to agent_actions table for post-mortem audit

Tiering:
  - `critical`  → Opus 4.7. Risk officer veto, PM sanity check, daily synth.
  - `routine`   → Sonnet 4.6. Technical analyst, sentiment analyst, critic.
  - `bulk`      → Sonnet 4.6 via Batch API (50% discount, 24h SLA). Hypothesis
                  generation, weekly trade-journal embeddings.

The brain NEVER places orders, edits risk params, or moves capital. Those
paths run through the existing deterministic Python in lib.risk_engine,
.claude/skills/execute-trade, etc. The brain only outputs structured
decisions (approve/veto/flag) that the orchestrator layer then enforces.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import anthropic  # type: ignore
except ImportError:
    anthropic = None  # type: ignore

from lib.anthropic_cost_tracker import track_call, should_allow  # noqa: E402
from lib.db import get_connection  # noqa: E402


MODEL_CRITICAL = "claude-opus-4-7"
MODEL_ROUTINE = "claude-sonnet-4-6"
MODEL_BULK = "claude-sonnet-4-6"  # routed via Batch API in brain.bulk()
MODEL_LIGHT = "claude-haiku-4-5"   # cheap tier for status updates, summaries, heartbeats


@dataclass
class BrainResponse:
    ok: bool
    text: str
    parsed: Optional[dict]
    model: str
    tier: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    usd_cost: float = 0.0
    elapsed_s: float = 0.0
    error: Optional[str] = None
    raw_response: Any = None

    @property
    def veto(self) -> bool:
        """True when the parsed payload contains an explicit veto verdict."""
        if not self.parsed:
            return False
        v = self.parsed.get("verdict") or self.parsed.get("action") or ""
        return str(v).upper() in {"VETO", "FAIL", "NO_BET", "REJECT"}


def _client() -> "anthropic.Anthropic":  # type: ignore
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed; pip install anthropic")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is empty")
    return anthropic.Anthropic(api_key=key)


def _resolve_model(tier: str) -> str:
    """Tier → concrete model ID.

    Tiers:
      critical  → Opus 4.7    : decisions that gate real trades, deep market analysis
      routine   → Sonnet 4.6  : adversarial critique, weekly narratives, hypothesis generation
      light     → Haiku 4.5   : status updates, heartbeat summaries, single-line outputs
      bulk      → Sonnet 4.6  : same model as routine but intended for Batch API (50% off, 24h SLA)
    Unknown tiers fall back to routine.
    """
    return {
        "critical": MODEL_CRITICAL,
        "routine": MODEL_ROUTINE,
        "light": MODEL_LIGHT,
        "bulk": MODEL_BULK,
    }.get(tier, MODEL_ROUTINE)


def _parse_json_from(text: str) -> Optional[dict]:
    """Tolerant JSON extraction. Agents are instructed to return JSON only, but
    Claude occasionally wraps in code fences or adds a preamble. Try strict
    parse first; fall back to greedy-brace extraction."""
    if not text:
        return None
    s = text.strip()
    # Strip markdown fences
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
    # Greedy braces fallback
    first = s.find("{")
    last = s.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(s[first : last + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _log_action(job: str, payload: dict) -> None:
    """Append to agent_actions table. Never raises."""
    try:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO agent_actions (timestamp, job, model, tier, payload_json, ok, usd_cost)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    job,
                    payload.get("model", ""),
                    payload.get("tier", ""),
                    json.dumps({k: v for k, v in payload.items() if k != "model"})[:8000],
                    1 if payload.get("ok") else 0,
                    float(payload.get("usd_cost") or 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[llm_brain] log_action failed (non-fatal): {e}")


def call(
    *,
    job: str,
    tier: str,
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    cache_system: bool = True,
    parse_json: bool = True,
    timeout: float = 60.0,
    fallback_parsed: Optional[dict] = None,
) -> BrainResponse:
    """Single synchronous LLM call with caching + cost tracking + schema parse.

    The system prompt is auto-marked as a cache breakpoint when cache_system=True
    (default), so repeat calls within 5 minutes pay the cached-input rate.
    Each agent persona is its own breakpoint; we don't try to chain across
    agents (they have different system prompts).

    On any error (missing key, monthly cap, schema parse fail), returns a
    BrainResponse with ok=False so the caller can fall back to deterministic
    behavior rather than crash.
    """
    allowed, reason = should_allow(job)
    if not allowed:
        msg = f"monthly cap reached, skipping {job}: {reason}"
        print(f"[llm_brain] {msg}")
        return BrainResponse(
            ok=False, text="", parsed=fallback_parsed,
            model="", tier=tier, error=reason,
        )

    if anthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"[llm_brain] anthropic unavailable or no key — fallback for {job}")
        return BrainResponse(
            ok=False, text="", parsed=fallback_parsed,
            model="", tier=tier, error="anthropic_unavailable",
        )

    model = _resolve_model(tier)
    started = time.time()
    try:
        client = _client()
        # Cache the system prompt — every persona is a stable, reusable block.
        system_block: Any
        if cache_system:
            system_block = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_block = system

        # Build kwargs — Opus 4.7+ deprecates the `temperature` parameter
        # (the API errors with `temperature is deprecated for this model`).
        # Sonnet 4.6 and older still accept it. Pass it only when supported
        # so we don't have to maintain a forked model list.
        create_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_block,
            "messages": [{"role": "user", "content": user}],
            "timeout": timeout,
        }
        if not model.startswith("claude-opus-4-7"):
            create_kwargs["temperature"] = temperature

        resp = client.messages.create(**create_kwargs)
        elapsed = time.time() - started

        # Extract text + token usage
        text = ""
        for block in (resp.content or []):
            if getattr(block, "type", "") == "text":
                text += getattr(block, "text", "")
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        cached_input = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0
        cache_create = int(getattr(usage, "cache_creation_input_tokens", 0) or 0) if usage else 0
        # Anthropic reports cache_read separately from input_tokens; we treat
        # cache_creation as regular input (writes are billed normally) and
        # cache_read at the discounted cached rate.
        non_cached_input = input_tokens + cache_create

        cost = track_call(
            job=job,
            model=model,
            input_tokens=non_cached_input,
            cached_input_tokens=cached_input,
            output_tokens=output_tokens,
            notes=f"elapsed={elapsed:.1f}s",
        )

        parsed = _parse_json_from(text) if parse_json else None

        result = BrainResponse(
            ok=True,
            text=text,
            parsed=parsed,
            model=model,
            tier=tier,
            input_tokens=non_cached_input,
            cached_input_tokens=cached_input,
            output_tokens=output_tokens,
            usd_cost=cost,
            elapsed_s=elapsed,
            raw_response=resp,
        )
        _log_action(job, {
            "model": model, "tier": tier, "ok": True,
            "input_tokens": non_cached_input,
            "cached_input_tokens": cached_input,
            "output_tokens": output_tokens,
            "usd_cost": cost,
            "elapsed_s": round(elapsed, 2),
            "parsed_keys": list(parsed.keys()) if parsed else None,
            "veto": (str(parsed.get("verdict") or "").upper() in {"VETO","FAIL","NO_BET"} if parsed else False),
        })
        return result
    except Exception as e:
        elapsed = time.time() - started
        print(f"[llm_brain] {job} call failed after {elapsed:.1f}s: {e}")
        _log_action(job, {
            "model": model, "tier": tier, "ok": False, "error": str(e)[:300],
            "elapsed_s": round(elapsed, 2),
        })
        return BrainResponse(
            ok=False, text="", parsed=fallback_parsed,
            model=model, tier=tier, error=str(e),
            elapsed_s=elapsed,
        )


def load_prompt(name: str) -> str:
    """Load a persona prompt from prompts/<name>.md, with a hard fallback.

    If the file doesn't exist (e.g. in a stripped-down test container), we
    return a minimal placeholder instead of crashing the cron.
    """
    path = os.path.join(PROJECT_ROOT, "prompts", f"{name}.md")
    if not os.path.exists(path):
        return f"You are the {name} agent. Return JSON only."
    with open(path) as f:
        return f.read()
