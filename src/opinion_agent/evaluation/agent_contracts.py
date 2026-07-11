"""Agent workflow contract checks independent of model accuracy."""

from collections import Counter
from typing import Any

from opinion_agent.agent.reviewer import review_selection_reason


REQUIRED_REPORT_FIELDS = {
    "event_id",
    "executive_summary",
    "attention_level",
    "sentiment_snapshot",
    "risk_signals",
    "disputed_sample_ids",
    "evidence_references",
    "review_status",
    "recommended_actions",
    "limitations",
}


def evaluate_agent_contract(
    request: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate one completed graph run against observable workflow contracts."""
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, passed: bool, detail: str) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    comments = request.get("comments", [])
    expected_ids = [
        str(comment.get("sample_id") or f"comment-{index}")
        for index, comment in enumerate(comments)
    ]
    sentiment_results = result.get("sentiment_results", [])
    result_ids = [str(item.get("sample_id", "")) for item in sentiment_results]
    identity_ok = (
        result_ids == expected_ids
        and len(result_ids) == len(set(result_ids))
        and all(result_ids)
    )
    record(
        "sample_identity_integrity",
        identity_ok,
        f"expected={expected_ids}; actual={result_ids}",
    )

    aggregate = result.get("aggregate_stats", {})
    counts = aggregate.get("counts", {})
    total = aggregate.get("total")
    aggregate_ok = (
        isinstance(counts, dict)
        and total == len(sentiment_results)
        and sum(counts.values()) == total
        and aggregate.get("scorable", 0) + aggregate.get("unscorable", 0) == total
    )
    record(
        "aggregate_consistency",
        aggregate_ok,
        f"results={len(sentiment_results)}; total={total}; counts={counts}",
    )

    report = result.get("analysis_report")
    report_ok = (
        isinstance(report, dict)
        and REQUIRED_REPORT_FIELDS.issubset(report)
        and report.get("event_id") == request.get("event_id")
        and bool(report.get("executive_summary"))
        and bool(report.get("recommended_actions"))
        and bool(report.get("limitations"))
    )
    missing_fields = (
        sorted(REQUIRED_REPORT_FIELDS - set(report)) if isinstance(report, dict) else sorted(REQUIRED_REPORT_FIELDS)
    )
    record(
        "briefing_contract",
        report_ok,
        f"missing_fields={missing_fields}; event_id={report.get('event_id') if isinstance(report, dict) else None}",
    )

    traces = result.get("tool_traces", [])
    trace_nodes = [str(trace.get("node", "")) for trace in traces]
    if "route_decision" in result:
        route = result["route_decision"]
        branch = "baseline_ready"
        if route.get("needs_review"):
            branch = "llm_review" if "llm_review" in trace_nodes else "review_required"
        expected_trace = [
            "sentiment_classifier",
            "sentiment_aggregator",
            "evidence_retriever",
            "review_router",
            branch,
            "briefing_composer",
        ]
    else:
        expected_trace = [
            "sentiment_classifier",
            "sentiment_aggregator",
            "briefing_composer",
        ]
    trace_order_ok = trace_nodes == expected_trace
    record(
        "trajectory_order",
        trace_order_ok,
        f"expected={expected_trace}; actual={trace_nodes}",
    )

    trace_metadata_ok = bool(traces) and len(trace_nodes) == len(set(trace_nodes)) and all(
        trace.get("status") in {"ok", "degraded", "error"}
        and isinstance(trace.get("duration_ms"), (int, float))
        and trace["duration_ms"] >= 0
        and isinstance(trace.get("details"), dict)
        for trace in traces
    )
    record(
        "trace_metadata",
        trace_metadata_ok,
        f"trace_count={len(traces)}; statuses={[trace.get('status') for trace in traces]}",
    )

    expected_disputed = [
        str(item.get("sample_id", ""))
        for item in sentiment_results
        if review_selection_reason(item) is not None
    ]
    disputed = report.get("disputed_sample_ids", []) if isinstance(report, dict) else []
    disputed_ok = disputed == expected_disputed and len(disputed) == len(set(disputed))
    record(
        "disputed_reference_integrity",
        disputed_ok,
        f"expected={expected_disputed}; actual={disputed}",
    )

    evidence = result.get("retrieved_evidence", [])
    references = report.get("evidence_references", []) if isinstance(report, dict) else []
    evidence_ids = [str(item.get("evidence_id", "")) for item in evidence]
    reference_ids = [str(item.get("evidence_id", "")) for item in references]
    reference_by_id = {str(item.get("evidence_id", "")): item for item in references}
    evidence_ok = (
        evidence_ids == reference_ids
        and len(evidence_ids) == len(set(evidence_ids))
        and all(item.get("event_id") != request.get("event_id") for item in evidence)
        and all(
            reference_by_id.get(str(item.get("evidence_id", "")), {}).get("source_url")
            == item.get("source_url")
            for item in evidence
        )
    )
    record(
        "evidence_provenance_integrity",
        evidence_ok,
        f"retrieved={evidence_ids}; referenced={reference_ids}",
    )

    route = result.get("route_decision")
    review_status = report.get("review_status") if isinstance(report, dict) else None
    errors = result.get("errors", [])
    if route is None:
        expected_status = "not_required"
    elif not route.get("needs_review"):
        expected_status = "not_required"
    elif result.get("review_result") is not None:
        expected_status = "llm_completed"
    elif errors:
        expected_status = "llm_failed"
    else:
        expected_status = "manual_required"
    route_ok = review_status == expected_status and all(
        error.get("recoverable") is True for error in errors
    )
    record(
        "review_fallback_consistency",
        route_ok,
        f"expected_status={expected_status}; actual_status={review_status}; errors={len(errors)}",
    )

    status_counts = Counter(check["passed"] for check in checks.values())
    failed_checks = [name for name, check in checks.items() if not check["passed"]]
    return {
        "passed": not failed_checks,
        "checks_passed": status_counts[True],
        "checks_total": len(checks),
        "failed_checks": failed_checks,
        "checks": checks,
    }
