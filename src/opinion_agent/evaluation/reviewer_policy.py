"""Replay LLM reviewer outputs under explicit, auditable override policies."""

from collections.abc import Sequence


def evaluate_override_policy(
    cases: Sequence[dict[str, object]],
    responses: Sequence[dict[str, object]],
    *,
    allowed_confidence: frozenset[str] | None = None,
    allowed_reasons: frozenset[str] | None = None,
) -> dict[str, object]:
    """Compare gated reviewer overrides with the original classifier baseline."""
    by_id = {str(response["sample_id"]): response for response in responses}
    selected = [case for case in cases if str(case["sample_id"]) in by_id]
    baseline_correct = final_correct = overrides = corrected = harmful = 0

    for case in selected:
        response = by_id[str(case["sample_id"])]
        baseline = str(case["xgb_label"])
        expected = str(case["expected_label"])
        reviewer_label = str(response["label"])
        confidence_ok = allowed_confidence is None or str(
            response.get("confidence", "")
        ) in allowed_confidence
        reason_ok = allowed_reasons is None or str(
            case.get("selection_reason", "")
        ) in allowed_reasons
        override = confidence_ok and reason_ok and reviewer_label != baseline
        final_label = reviewer_label if override else baseline

        baseline_was_correct = baseline == expected
        final_is_correct = final_label == expected
        baseline_correct += baseline_was_correct
        final_correct += final_is_correct
        overrides += override
        corrected += override and not baseline_was_correct and final_is_correct
        harmful += override and baseline_was_correct and not final_is_correct

    count = len(selected)
    return {
        "cases": count,
        "overrides": overrides,
        "override_rate": overrides / count if count else 0.0,
        "baseline_accuracy": baseline_correct / count if count else 0.0,
        "final_accuracy": final_correct / count if count else 0.0,
        "net_accuracy_change": (final_correct - baseline_correct) / count if count else 0.0,
        "corrected_errors": corrected,
        "harmful_overrides": harmful,
    }
