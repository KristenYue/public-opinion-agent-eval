"""Provider-independent evaluation for structured comment reviewers."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from statistics import median
from time import perf_counter
from typing import Protocol
import math


class StructuredReviewer(Protocol):
    def review(self, state: dict[str, object]) -> dict[str, object]: ...


def run_reviewer_benchmark(
    cases: Sequence[dict[str, object]],
    reviewer: StructuredReviewer,
    *,
    batch_size: int = 8,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Run selected cases through a reviewer and score contract + task behavior."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    selected = [case for case in cases if case.get("selected_for_review")]
    expected_by_id = {str(case["sample_id"]): str(case["expected_label"]) for case in selected}
    baseline_by_id = {str(case["sample_id"]): str(case["xgb_label"]) for case in selected}
    grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for case in selected:
        grouped[str(case["event_id"])].append(case)

    batches: list[list[dict[str, object]]] = []
    for event_id in sorted(grouped):
        event_cases = grouped[event_id]
        batches.extend(
            event_cases[index : index + batch_size]
            for index in range(0, len(event_cases), batch_size)
        )

    responses: list[dict[str, object]] = []
    successful_batches = 0
    total_attempts = 0
    usage_totals: Counter[str] = Counter()
    latencies: list[float] = []
    failures: list[dict[str, str]] = []
    for batch_index, batch in enumerate(batches, start=1):
        state = _review_state(batch, batch_index)
        started = perf_counter()
        try:
            result = reviewer.review(state)
            successful_batches += 1
            total_attempts += int(result.get("attempts", 1) or 1)
            usage = result.get("usage", {})
            if isinstance(usage, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_chars"):
                    usage_totals[key] += int(usage.get(key, 0) or 0)
            for item in result.get("items", []):
                responses.append(
                    {
                        **dict(item),
                        "batch_id": state["request_id"],
                        "reviewer": result.get("reviewer", "unknown"),
                    }
                )
        except Exception as exc:
            failures.append(
                {
                    "batch_id": str(state["request_id"]),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        latencies.append((perf_counter() - started) * 1000)

    response_ids = [str(item.get("sample_id", "")) for item in responses]
    counts = Counter(response_ids)
    response_by_id = {
        sample_id: item
        for item in responses
        if (sample_id := str(item.get("sample_id", ""))) in expected_by_id
    }
    duplicate_ids = sorted(sample_id for sample_id, count in counts.items() if count > 1)
    unexpected_ids = sorted(set(response_ids) - set(expected_by_id))
    missing_ids = sorted(set(expected_by_id) - set(response_by_id))
    correct = sum(
        str(response_by_id[sample_id].get("label")) == expected
        for sample_id, expected in expected_by_id.items()
        if sample_id in response_by_id
    )
    baseline_errors = [
        sample_id
        for sample_id, expected in expected_by_id.items()
        if baseline_by_id[sample_id] != expected
    ]
    corrected_errors = sum(
        sample_id in response_by_id
        and str(response_by_id[sample_id].get("label")) == expected_by_id[sample_id]
        for sample_id in baseline_errors
    )
    rationale_coverage = sum(
        bool(str(item.get("rationale", "")).strip()) for item in response_by_id.values()
    )

    metrics = {
        "status": "completed" if not failures else "completed_with_failures",
        "selected_cases": len(selected),
        "batches": len(batches),
        "successful_batches": successful_batches,
        "http_attempts": total_attempts,
        "average_attempts_per_successful_batch": (
            total_attempts / successful_batches if successful_batches else 0.0
        ),
        "structured_batch_success_rate": (
            successful_batches / len(batches) if batches else 0.0
        ),
        "item_coverage": len(response_by_id) / len(selected) if selected else 0.0,
        "label_accuracy_on_returned_items": (
            correct / len(response_by_id) if response_by_id else 0.0
        ),
        "baseline_errors_in_selected_cases": len(baseline_errors),
        "corrected_baseline_errors": corrected_errors,
        "baseline_error_correction_rate": (
            corrected_errors / len(baseline_errors) if baseline_errors else 0.0
        ),
        "rationale_coverage": (
            rationale_coverage / len(response_by_id) if response_by_id else 0.0
        ),
        "usage": {
            "prompt_tokens": usage_totals["prompt_tokens"],
            "completion_tokens": usage_totals["completion_tokens"],
            "total_tokens": usage_totals["total_tokens"],
            "input_chars": usage_totals["input_chars"],
            "note": "Provider pricing is not inferred; token counts support explicit cost calculation.",
        },
        "missing_sample_ids": missing_ids,
        "unexpected_sample_ids": unexpected_ids,
        "duplicate_sample_ids": duplicate_ids,
        "latency_ms": {
            "median": median(latencies) if latencies else 0.0,
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies) if latencies else 0.0,
        },
        "failures": failures,
    }
    return metrics, responses


def _review_state(batch: list[dict[str, object]], batch_index: int) -> dict[str, object]:
    event_id = str(batch[0]["event_id"])
    return {
        "request_id": f"review-eval-{event_id}-{batch_index}",
        "event_id": event_id,
        "query": "结合评论与原帖上下文，对争议评论进行情绪复核。",
        "comments": [
            {
                "sample_id": str(case["sample_id"]),
                "text": str(case["text"]),
                "context": str(case.get("context", "")),
                "source_url": str(case.get("source_url", "")),
            }
            for case in batch
        ],
        "sentiment_results": [
            {
                "sample_id": str(case["sample_id"]),
                "text": str(case["text"]),
                "label": str(case["xgb_label"]),
                "confidence": float(case.get("xgb_confidence") or 0.0),
                "probabilities": {},
                "source": "legacy_xgboost",
                "secondary_label": str(case["secondary_label"]),
                "secondary_score": float(case.get("secondary_score") or 0.0),
                "models_agree": case["xgb_label"] == case["secondary_label"],
            }
            for case in batch
        ],
        "retrieved_evidence": [],
        "tool_traces": [],
        "errors": [],
    }


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)
    return ordered[index]
