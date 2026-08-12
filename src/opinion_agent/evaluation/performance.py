"""Performance and routing summaries for repeated agent runs."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


PATHS = ("fast_path", "qwen_reviewed", "manual_required")
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "input_chars")


def percentile(values: list[float], probability: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def extract_path_counts(result: dict[str, Any]) -> Counter[str]:
    """Count comment-level final paths, including offline manual fallback."""
    counts: Counter[str] = Counter()
    sentiment_results = result.get("sentiment_results", [])
    explicit_paths = [
        item.get("decision_path")
        for item in sentiment_results
        if item.get("decision_path") in PATHS
    ]
    if explicit_paths:
        counts.update(str(path) for path in explicit_paths)
        return counts

    report = result.get("analysis_report", {})
    review_status = report.get("review_status")
    for item in result.get("route_decision", {}).get("items", []):
        if not item.get("needs_review"):
            counts["fast_path"] += 1
        elif review_status == "llm_completed":
            counts["qwen_reviewed"] += 1
        else:
            counts["manual_required"] += 1
    return counts


def extract_usage(result: dict[str, Any]) -> dict[str, int]:
    """Extract provider-reported usage without estimating missing token counts."""
    usage = result.get("review_result") or {}
    usage = usage.get("usage", {}) if isinstance(usage, dict) else {}
    if not usage:
        for trace in result.get("tool_traces", []):
            if trace.get("node") == "llm_review":
                usage = trace.get("details", {}).get("usage", {})
                break
    return {field: int(usage.get(field, 0) or 0) for field in TOKEN_FIELDS}


def summarize_runs(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate wall latency, node latency, routes, usage, and failures."""
    if not records:
        raise ValueError("at least one run record is required")

    wall_values = [float(record["wall_latency_ms"]) for record in records]
    node_values: dict[str, list[float]] = defaultdict(list)
    node_statuses: Counter[str] = Counter()
    path_counts: Counter[str] = Counter()
    usage_totals: Counter[str] = Counter()
    error_types: Counter[str] = Counter()

    for record in records:
        result = record["result"]
        path_counts.update(extract_path_counts(result))
        usage_totals.update(extract_usage(result))
        for trace in result.get("tool_traces", []):
            node = str(trace.get("node", "unknown"))
            node_values[node].append(float(trace.get("duration_ms", 0.0) or 0.0))
            node_statuses[f"{node}:{trace.get('status', 'unknown')}"] += 1
        for error in result.get("errors", []):
            error_types[str(error.get("error_type", "unknown"))] += 1

    total_paths = sum(path_counts.values())
    latency = _latency_summary(wall_values)
    return {
        "run_count": len(records),
        "wall_latency_ms": latency,
        "node_latency_ms": {
            node: _latency_summary(values) for node, values in sorted(node_values.items())
        },
        "path_counts": {path: path_counts.get(path, 0) for path in PATHS},
        "path_rates": {
            path: round(path_counts.get(path, 0) / total_paths, 6) if total_paths else 0.0
            for path in PATHS
        },
        "provider_reported_usage": {
            field: usage_totals.get(field, 0) for field in TOKEN_FIELDS
        },
        "node_status_counts": dict(sorted(node_statuses.items())),
        "error_type_counts": dict(sorted(error_types.items())),
        "failed_run_count": sum(bool(record["result"].get("errors")) for record in records),
    }


def _latency_summary(values: list[float]) -> dict[str, float]:
    return {
        "min": round(min(values), 3),
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
        "mean": round(sum(values) / len(values), 3),
    }
