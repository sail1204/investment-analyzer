from __future__ import annotations

from logic.evaluations.common import EvaluationResult, clamp_int, is_nonempty_string

VALID_DRIFT_SIGNALS = {"Stable", "Updated", "Contradicted", "Exogenous Shock"}
VALID_ERROR_TYPES = {"Exogenous Shock", "Timing Error", "Thesis Error", "Data Gap", None}


def evaluate_self_corrector_output(output: dict, prior_snapshot: dict) -> EvaluationResult:
    normalized = {
        "drift_signal": output.get("drift_signal"),
        "error_type": output.get("error_type"),
        "explanation": output.get("explanation"),
        "updated_thesis": output.get("updated_thesis") or prior_snapshot.get("thesis", ""),
        "updated_conviction": clamp_int(
            output.get("updated_conviction"),
            1,
            10,
            prior_snapshot.get("conviction") or 1,
        ),
    }
    issues: list[str] = []

    if normalized["drift_signal"] not in VALID_DRIFT_SIGNALS:
        issues.append("invalid_drift_signal")
        normalized["drift_signal"] = "Stable"
    if normalized["error_type"] not in VALID_ERROR_TYPES:
        issues.append("invalid_error_type")
        normalized["error_type"] = None
    if not is_nonempty_string(normalized["explanation"], min_len=10):
        issues.append("missing_explanation")
    if not is_nonempty_string(normalized["updated_thesis"], min_len=20):
        issues.append("missing_updated_thesis")
        normalized["updated_thesis"] = prior_snapshot.get("thesis", "")
    if normalized["drift_signal"] == "Contradicted" and normalized["error_type"] is None:
        issues.append("contradicted_without_error_type")

    should_retry = any(
        issue in issues
        for issue in (
            "invalid_drift_signal",
            "missing_explanation",
            "missing_updated_thesis",
            "contradicted_without_error_type",
        )
    )

    return EvaluationResult(
        should_retry=should_retry,
        issues=issues,
        normalized_output=normalized,
    )
