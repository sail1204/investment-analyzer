from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

MAX_LOOKBACK_WEEKS = 12
DECAY_PER_WEEK = 0.85


def _round(value: float) -> float:
    return round(value, 3)


def _run_date_to_week_index(run_date: str) -> int | None:
    try:
        year_str, week_str = run_date.split("-")
        year = int(year_str)
        week = int(week_str)
        return year * 53 + week
    except (ValueError, AttributeError):
        return None


def _latest_week_index(rows: list[dict]) -> int | None:
    indices = [_run_date_to_week_index(row.get("run_date", "")) for row in rows]
    valid = [idx for idx in indices if idx is not None]
    return max(valid) if valid else None


def _row_weight(row: dict, latest_week_idx: int | None) -> float:
    if latest_week_idx is None:
        return 1.0
    week_idx = _run_date_to_week_index(row.get("run_date", ""))
    if week_idx is None:
        return 1.0
    weeks_ago = max(0, latest_week_idx - week_idx)
    if weeks_ago > MAX_LOOKBACK_WEEKS:
        return 0.0
    return DECAY_PER_WEEK ** weeks_ago


def build_learning_state(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Convert correction history into:
      1. sector-level learning state used by deterministic logic
      2. prompt hints consumed by LLM-driven agents
    """
    latest_week_idx = _latest_week_index(rows)
    sector_rows: dict[str, list[dict]] = defaultdict(list)
    global_error_counts: defaultdict[str, float] = defaultdict(float)

    for row in rows:
        weight = _row_weight(row, latest_week_idx)
        if weight <= 0:
            continue
        sector = row.get("sector") or "Unknown"
        weighted_row = {**row, "_weight": weight}
        sector_rows[sector].append(weighted_row)
        error_type = row.get("error_type")
        if error_type:
            global_error_counts[error_type] += weight

    learning_state: list[dict] = []
    prompt_hints: list[dict] = []

    for sector, items in sector_rows.items():
        total_weight = sum(item["_weight"] for item in items)
        raw_total = len(items)
        drift_weights: defaultdict[str, float] = defaultdict(float)
        for item in items:
            drift_weights[item.get("drift_signal") or "Unknown"] += item["_weight"]
        contradicted = drift_weights.get("Contradicted", 0.0)
        updated = drift_weights.get("Updated", 0.0)
        stable = drift_weights.get("Stable", 0.0)
        contradiction_rate = contradicted / total_weight if total_weight else 0.0
        penalty = 0.0
        caution = "normal"
        if raw_total >= 2 and contradiction_rate >= 0.5:
            penalty = 12.0
            caution = "high"
        elif raw_total >= 2 and contradiction_rate >= 0.34:
            penalty = 6.0
            caution = "medium"

        top_error_type = None
        error_counts: defaultdict[str, float] = defaultdict(float)
        for item in items:
            error_type = item.get("error_type")
            if error_type:
                error_counts[error_type] += item["_weight"]
        if error_counts:
            top_error_type = max(error_counts.items(), key=lambda kv: kv[1])[0]

        value = {
            "sector": sector,
            "recent_corrections": raw_total,
            "effective_weight": _round(total_weight),
            "contradiction_rate": _round(contradiction_rate),
            "updated_rate": _round(updated / total_weight if total_weight else 0.0),
            "stable_rate": _round(stable / total_weight if total_weight else 0.0),
            "sector_penalty": penalty,
            "caution_level": caution,
            "top_error_type": top_error_type,
            "decay_per_week": DECAY_PER_WEEK,
            "max_lookback_weeks": MAX_LOOKBACK_WEEKS,
        }
        learning_state.append({
            "state_type": "sector_learning",
            "state_key": sector,
            "value": value,
        })

        if caution != "normal":
            prompt_hints.append({
                "agent_name": "researcher",
                "scope_type": "sector",
                "scope_key": sector,
                "hint_text": (
                    f"Recent corrections in {sector} show elevated contradiction risk. "
                    f"Be conservative, state evidence gaps clearly, and stress-test leverage, catalysts, and thesis fragility."
                ),
                "strength": 1.0 + penalty / 12.0,
            })
            prompt_hints.append({
                "agent_name": "portfolio_manager",
                "scope_type": "sector",
                "scope_key": sector,
                "hint_text": (
                    f"Recent corrected theses in {sector} have been less reliable. "
                    f"Prefer smaller allocations, stronger catalysts, and clearer downside protection."
                ),
                "strength": 1.0 + penalty / 12.0,
            })
            prompt_hints.append({
                "agent_name": "self_corrector",
                "scope_type": "sector",
                "scope_key": sector,
                "hint_text": (
                    f"{sector} has shown repeat thesis failures recently. "
                    f"Be strict when deciding whether the prior thesis was actually contradicted."
                ),
                "strength": 1.0 + penalty / 12.0,
            })

    for error_type, count in sorted(global_error_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]:
        if count < 1.5:
            continue
        hint = None
        if error_type == "Data Gap":
            hint = "Recent failures often came from missing available signals. Explicitly call out missing evidence and avoid overconfident conclusions."
        elif error_type == "Thesis Error":
            hint = "Recent failures often came from flawed core reasoning. Prefer narrower claims and tie each thesis claim directly to evidence."
        elif error_type == "Timing Error":
            hint = "Recent failures often came from timeframe mismatch. Separate long-term value from near-term catalyst timing."
        elif error_type == "Exogenous Shock":
            hint = "Recent failures include exogenous shocks. Distinguish thesis failure from external events outside the original model."

        if hint:
            for agent_name in ("researcher", "self_corrector", "portfolio_manager"):
                prompt_hints.append({
                    "agent_name": agent_name,
                    "scope_type": "global",
                    "scope_key": "all",
                    "hint_text": hint,
                    "strength": 1.0 + min(count / 2.5, 1.0),
                })

    return learning_state, prompt_hints
