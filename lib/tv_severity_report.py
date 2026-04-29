"""Pretty-print the TV severity sweep results — passes, fails, top performers."""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def latest_report() -> str | None:
    files = sorted(glob.glob(os.path.join(PROJECT_ROOT, "data", "backtests", "tv_severity_*.json")))
    return files[-1] if files else None


def render(report_path: str) -> str:
    with open(report_path) as f:
        rep = json.load(f)
    lines = [
        f"# TV Severity Sweep — {report_path.split('/')[-1]}",
        "",
        f"- started:  {rep.get('started_at')}",
        f"- ended:    {rep.get('ended_at')}",
        f"- days:     {rep.get('days')}",
        f"- min_trades: {rep.get('min_trades')}",
        f"- symbols:  {len(rep.get('symbols', []))}",
        f"- timeframes: {rep.get('timeframes')}",
        "",
        f"**PASS**: {rep.get('passed', 0)} · **FAIL**: {rep.get('failed', 0)} · **ERROR**: {rep.get('errored', 0)}",
        "",
    ]
    strategies = rep.get("strategies", [])
    passed = [s for s in strategies if s.get("passed")]
    failed = [s for s in strategies if not s.get("passed")]

    passed.sort(key=lambda s: -s.get("avg_pnl_pct", 0))
    failed.sort(key=lambda s: -s.get("trades", 0))

    if passed:
        lines.append("## Passed (≥ gate trades)")
        lines.append("")
        lines.append("| Strategy | Trades | Win % | Avg R |")
        lines.append("|---|---:|---:|---:|")
        for s in passed:
            lines.append(
                f"| `{s['strategy_id']}` | {s['trades']} | "
                f"{s.get('win_rate', 0)*100:.0f}% | {s.get('avg_pnl_pct', 0):+.2f}R |"
            )
        lines.append("")

    if failed:
        lines.append("## Failed (below gate)")
        lines.append("")
        lines.append("| Strategy | Trades | Reason |")
        lines.append("|---|---:|---|")
        for s in failed[:30]:
            lines.append(f"| `{s['strategy_id']}` | {s['trades']} | {s.get('reason')} |")
        if len(failed) > 30:
            lines.append(f"| _… {len(failed) - 30} more_ | | |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", help="Path to a tv_severity_*.json report (default: latest)")
    ap.add_argument("--save", action="store_true", help="Also write to memory/TV-SEVERITY-REPORT.md")
    args = ap.parse_args()

    p = args.path or latest_report()
    if not p:
        print("No tv_severity report found yet — run lib/tv_severity_runner.py first.")
        return
    md = render(p)
    print(md)
    if args.save:
        out = Path(PROJECT_ROOT) / "memory" / "TV-SEVERITY-REPORT.md"
        out.write_text(md + "\n")
        print(f"\n[tv_severity_report] saved → {out}")


if __name__ == "__main__":
    main()
