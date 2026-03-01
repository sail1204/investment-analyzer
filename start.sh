#!/bin/bash
set -e

echo "=== Investment Analyzer startup ==="

# Init DB and seed watchlist (idempotent — safe to run every time)
python3 -m memory.database

# Check portfolio and optionally seed — run in background so dashboard starts immediately
(
  PORTFOLIO_COUNT=$(python3 -c "
from memory.database import init_db, get_portfolio
init_db()
print(len(get_portfolio()))
" 2>/dev/null || echo "0")

  if [ "$PORTFOLIO_COUNT" = "0" ]; then
    echo "Portfolio is empty — running initial daily agent in background..."
    python3 -m workflows.run_daily --force || echo "Initial run failed."
  else
    echo "Portfolio has $PORTFOLIO_COUNT positions — skipping initial run."
  fi

  # Start the daily scheduler (weekdays noon)
  echo "Starting daily scheduler..."
  python3 -m workflows.run_daily --schedule
) &

# Start the web dashboard immediately (foreground — Railway health-checks this)
echo "Starting dashboard on port ${PORT:-8080}..."
exec python3 -m workflows.dashboard.server
