#!/bin/bash
set -e

echo "=== Investment Analyzer startup ==="

# Init DB and seed watchlist (idempotent — safe to run every time)
python3 -m data.database

# Start the daily scheduler in the background (weekdays noon)
echo "Starting daily scheduler..."
python3 -m agent.run_daily --schedule &

# Start the web dashboard (foreground — Railway monitors this process)
echo "Starting dashboard on port ${PORT:-8080}..."
exec python3 -m dashboard.server
