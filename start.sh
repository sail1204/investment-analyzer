#!/bin/bash
set -e

echo "=== Investment Analyzer startup ==="

# Init DB and seed watchlist (idempotent — safe to run every time)
python3 -m data.database

# Run the agent immediately on first deploy (when portfolio is empty)
PORTFOLIO_COUNT=$(python3 -c "
from data.database import init_db, get_portfolio
init_db()
print(len(get_portfolio()))
" 2>/dev/null || echo "0")

if [ "$PORTFOLIO_COUNT" = "0" ]; then
  echo "Portfolio is empty — running initial daily agent..."
  python3 -m agent.run_daily --force || echo "Initial run failed, continuing..."
else
  echo "Portfolio has $PORTFOLIO_COUNT positions — skipping initial run."
fi

# Start the daily scheduler in the background (weekdays noon)
echo "Starting daily scheduler..."
python3 -m agent.run_daily --schedule &

# Start the web dashboard (foreground — Railway monitors this process)
echo "Starting dashboard on port ${PORT:-8080}..."
exec python3 -m dashboard.server
