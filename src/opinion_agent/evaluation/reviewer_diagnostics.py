"""Aggregate diagnostics for frozen reviewer responses."""

from __future__ import annotations

from collections import Counter
from typing import Any


CONFIDENCE_LEVELS = ("High", "Medium", "Low")


def diagnose_reviewer(
    rows: list[dict[str, Any]],
    responses: dict[str, dict[str, Any]],
    *,
    threshold: float,
    short_text_max_chars: int,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("reviewer diagnostics require at least one row")

    missing = [str(row["sample_id"]) for row in rows if str(row["sample_id"]) not in responses]
    if missing:
        raise ValueError(f"missing reviewer responses for {len(missing)} rows")

    confidence_totals: Counter[str] = Counter()
    confidence_correct: Counter[str] = Counter()
    unconditional = Counter()
    governed = Counter()
    baseline_correct = qwen_correct = governed_correct = 0
    selective_truth_count = selective_correct = 0

    for row in rows:
        response = responses[str(row["sample_id"])]
        gold = str(row["gold"])
        baseline = str(row["xgb_label"])
        qwen = str(response["label"])
        confidence = str(response["confidence"])
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"unsupported reviewer confidence: {confidence}")

        baseline_is_correct = baseline == gold
        qwen_is_correct = qwen == gold
        baseline_correct += baseline_is_correct
        qwen_correct += qwen_is_correct
        confidence_totals[confidence] += 1
        confidence_correct[confidence] += qwen_is_correct

        if qwen != baseline:
            unconditional["overrides"] += 1
            if not baseline_is_correct and qwen_is_correct:
                unconditional["corrected"] += 1
            elif baseline_is_correct and not qwen_is_correct:
                unconditional["harmful"] += 1
            else:
                unconditional["wrong_to_wrong"] += 1

        needs_review = (
            baseline != str(row["secondary_label"])
            or float(row["xgb_confidence"]) < threshold
            or len(str(row["content"]).strip()) <= short_text_max_chars
        )
        if not needs_review:
            chosen = baseline
            governed["fast_path"] += 1
            selective_truth_count += 1
            selective_correct += chosen == gold
        elif confidence == "High":
            chosen = qwen
            governed["qwen_reviewed"] += 1
            selective_truth_count += 1
            selective_correct += chosen == gold
            if qwen != baseline:
                governed["overrides"] += 1
                if not baseline_is_correct and qwen_is_correct:
                    governed["corrected"] += 1
                elif baseline_is_correct and not qwen_is_correct:
                    governed["harmful"] += 1
                else:
                    governed["wrong_to_wrong"] += 1
        else:
            chosen = baseline
            governed["manual_required"] += 1
        governed_correct += chosen == gold

    count = len(rows)
    return {
        "sample_count": count,
        "baseline_accuracy": baseline_correct / count,
        "unconditional_qwen_accuracy": qwen_correct / count,
        "confidence_strata": {
            level: {
                "count": confidence_totals[level],
                "accuracy": (
                    confidence_correct[level] / confidence_totals[level]
                    if confidence_totals[level]
                    else None
                ),
            }
            for level in CONFIDENCE_LEVELS
        },
        "unconditional_override": _override_summary(unconditional),
        "governed_policy": {
            "threshold": threshold,
            "short_text_max_chars": short_text_max_chars,
            "path_counts": {
                path: governed[path]
                for path in ("fast_path", "qwen_reviewed", "manual_required")
            },
            "automatic_accuracy_without_human": governed_correct / count,
            "selective_auto_accuracy": (
                selective_correct / selective_truth_count if selective_truth_count else 0.0
            ),
            "auto_coverage": selective_truth_count / count,
            **_override_summary(governed),
        },
    }


def _override_summary(counts: Counter[str]) -> dict[str, int]:
    corrected = counts["corrected"]
    harmful = counts["harmful"]
    return {
        "overrides": counts["overrides"],
        "corrected": corrected,
        "harmful": harmful,
        "wrong_to_wrong": counts["wrong_to_wrong"],
        "net_corrections": corrected - harmful,
    }
