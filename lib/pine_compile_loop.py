"""Pine Script compile loop — edit → compile → check → fix cycle via MCP.

Wraps pine_smart_compile, pine_get_errors, and pine_get_console so the
self-improve agent (and any future strategy author) can iterate on Pine
scripts without leaving Python. All calls proxy through a caller-provided
`mcp_call` so this module stays import-cheap outside the agent layer.

Typical usage from the agent:
    from lib.pine_compile_loop import compile_and_validate, load_pine_source

    source = load_pine_source("pine/strategies/fvg_detector.pine")
    result = compile_and_validate(mcp_call, source, script_name="FVGDetector")
    if result["ok"]:
        print("Compiled — errors:", result["errors"])
    else:
        print("Errors:", result["errors"])
        print("Console:", result["console"])
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PINE_DIR = os.path.join(PROJECT_ROOT, "pine")


def load_pine_source(relative_path: str) -> str:
    """Read a Pine script file relative to the project root."""
    full = os.path.join(PROJECT_ROOT, relative_path)
    with open(full) as f:
        return f.read()


def compile_and_validate(
    mcp_call: Callable,
    source: str,
    script_name: Optional[str] = None,
    max_fix_attempts: int = 3,
) -> dict:
    """Compile Pine source via MCP, collect errors, return a result dict.

    Args:
        mcp_call: agent proxy for mcp__tradingview__* tools.
        source: Pine v5 source code string.
        script_name: human label for logging (e.g. "FVGDetector").
        max_fix_attempts: how many compile attempts before giving up.
            Each attempt uses pine_smart_compile which auto-patches common
            syntax issues; more than 3 attempts rarely help.

    Returns:
        {
          "ok": bool,          # True = compiled with 0 errors
          "errors": list[str], # error messages (empty on success)
          "warnings": list[str],
          "console": str,      # last pine_get_console output
          "attempts": int,
        }
    """
    tag = script_name or "pine_script"
    errors: list[str] = []
    warnings: list[str] = []
    console_output = ""

    for attempt in range(1, max_fix_attempts + 1):
        print(f"[pine_compile_loop] {tag} attempt {attempt}/{max_fix_attempts}")

        # Inject source and smart-compile (auto-patches deprecations)
        try:
            mcp_call("pine_set_source", source=source)
            mcp_call("pine_smart_compile")
        except Exception as e:
            errors = [f"MCP call failed: {e}"]
            break

        # Collect errors
        try:
            err_result = mcp_call("pine_get_errors") or {}
            raw_errors = err_result.get("errors") or []
            errors = [str(e) for e in raw_errors]
            warnings = [str(w) for w in (err_result.get("warnings") or [])]
        except Exception as e:
            errors = [f"pine_get_errors failed: {e}"]
            break

        # Collect console output (script log.info / runtime messages)
        try:
            console_result = mcp_call("pine_get_console") or {}
            console_output = console_result.get("output") or console_result.get("text") or ""
        except Exception:
            console_output = ""

        if not errors:
            print(f"[pine_compile_loop] {tag} compiled OK (attempt {attempt})")
            break

        print(f"[pine_compile_loop] {tag} errors: {errors}")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "console": console_output,
        "attempts": attempt,
    }


def compile_file(
    mcp_call: Callable,
    pine_relative_path: str,
    **kwargs,
) -> dict:
    """Convenience wrapper: load a .pine file and compile it."""
    source = load_pine_source(pine_relative_path)
    script_name = Path(pine_relative_path).stem
    return compile_and_validate(mcp_call, source, script_name=script_name, **kwargs)


def compile_all_strategies(mcp_call: Callable) -> dict[str, dict]:
    """Compile every .pine file in pine/strategies/ and return results keyed by stem."""
    strat_dir = os.path.join(PINE_DIR, "strategies")
    results: dict[str, dict] = {}
    for path in sorted(Path(strat_dir).glob("*.pine")):
        rel = os.path.relpath(str(path), PROJECT_ROOT)
        results[path.stem] = compile_file(mcp_call, rel)
    return results
