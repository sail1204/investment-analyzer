from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvaluationResult:
    should_retry: bool
    issues: list[str]
    normalized_output: dict


def is_nonempty_string(value, *, min_len: int = 1) -> bool:
    return isinstance(value, str) and len(value.strip()) >= min_len


def clamp_int(value, lower: int, upper: int, default: int) -> int:
    try:
        return max(lower, min(upper, int(value)))
    except (TypeError, ValueError):
        return default


def coerce_string_list(value, *, max_items: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                result.append(text)
        if len(result) >= max_items:
            break
    return result
