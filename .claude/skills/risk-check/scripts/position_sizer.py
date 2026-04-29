"""Position sizing calculator. Wraps lib/risk_engine for CLI usage."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.risk_engine import calculate_position_size


def main():
    parser = argparse.ArgumentParser(description="Calculate position size based on risk parameters")
    parser.add_argument("--capital", type=float, required=True, help="Account capital in USD")
    parser.add_argument("--entry", type=float, required=True, help="Entry price")
    parser.add_argument("--stop", type=float, required=True, help="Stop loss price")
    parser.add_argument("--risk-pct", type=float, default=2.0, help="Max risk % per trade (default: 2%)")
    args = parser.parse_args()

    result = calculate_position_size(
        capital=args.capital,
        entry_price=args.entry,
        stop_loss_price=args.stop,
        max_risk_pct=args.risk_pct,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
