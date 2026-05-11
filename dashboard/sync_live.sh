#!/bin/bash
# Continuous sync of live Modal Volume into local data/ for the dashboard.
# Run alongside `python3 dashboard/app.py`. Polls every 60s.
set -u
cd "$(dirname "$0")/.."

while true; do
  python3 -m modal volume get trading-data /db/trading.db data/db/trading.db --force >/dev/null 2>&1
  TODAY=$(date -u +%Y-%m-%d)
  python3 -m modal volume get trading-data "/signals/${TODAY}" data/signals/ --force >/dev/null 2>&1
  echo "[$(date -u +%H:%M:%S)] synced"
  sleep 60
done
