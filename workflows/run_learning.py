"""
Deterministic learning pass.

Reads recent correction history and converts it into:
  - sector-level learning state for deterministic portfolio/screener logic
  - prompt hints for future agent runs

Uses recency-weighted correction history:
  - max lookback: 12 weekly runs
  - weekly decay factor: 0.85
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run(limit: int = 200, run_date: str | None = None) -> dict:
    from logic.learning.self_correction import build_learning_state
    from memory.database import (
        current_run_date,
        get_learning_rows,
        replace_learning_state,
        replace_prompt_hints,
    )

    run_date = run_date or current_run_date()
    logger.info("[Learning] Building learning state from correction history")
    rows = get_learning_rows(limit=limit)
    learning_state, prompt_hints = build_learning_state(rows)
    replace_learning_state(learning_state, run_date)
    replace_prompt_hints(prompt_hints, run_date)

    logger.info(
        f"[Learning] Saved {len(learning_state)} learning-state rows and {len(prompt_hints)} prompt hints"
    )
    return {
        "learning_state_rows": len(learning_state),
        "prompt_hints": len(prompt_hints),
    }


if __name__ == "__main__":
    run()
