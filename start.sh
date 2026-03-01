#!/bin/bash
set -e

echo "=== Investment Analyzer startup ==="

# Ensure the DB directory exists (required when Railway mounts a volume at /app/data)
DB_DIR="$(dirname "${DB_PATH:-memory/investment_analyzer.db}")"
mkdir -p "$DB_DIR"
echo "DB directory: $DB_DIR"

# Init DB and seed watchlist — non-fatal so the dashboard always starts
python3 -m memory.database || echo "WARNING: DB init returned non-zero, continuing..."

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
