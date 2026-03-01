from __future__ import annotations

from logic.evaluations.common import EvaluationResult, clamp_int, coerce_string_list, is_nonempty_string

VALID_VALUATION_SIGNALS = {"Cheap", "Fair", "Expensive"}


def evaluate_researcher_output(output: dict) -> EvaluationResult:
    normalized = {
        "thesis": output.get("thesis"),
        "key_risk": output.get("key_risk"),
        "catalyst": output.get("catalyst"),
        "second_order_effects": coerce_string_list(output.get("second_order_effects")),
        "conviction": clamp_int(output.get("conviction"), 1, 10, 1),
        "valuation_signal": output.get("valuation_signal", "Fair"),
    }
    issues: list[str] = []

    if not is_nonempty_string(normalized["thesis"], min_len=40):
        issues.append("missing_or_short_thesis")
    if not is_nonempty_string(normalized["key_risk"], min_len=5):
        issues.append("missing_key_risk")
    if not is_nonempty_string(normalized["catalyst"], min_len=5):
        issues.append("missing_catalyst")
    if normalized["valuation_signal"] not in VALID_VALUATION_SIGNALS:
        issues.append("invalid_valuation_signal")
        normalized["valuation_signal"] = "Fair"
    if not normalized["second_order_effects"]:
        issues.append("missing_second_order_effects")

    should_retry = any(
        issue in issues
        for issue in (
            "missing_or_short_thesis",
            "missing_key_risk",
            "missing_catalyst",
            "invalid_valuation_signal",
        )
    )

    return EvaluationResult(
        should_retry=should_retry,
        issues=issues,
        normalized_output=normalized,
    )
