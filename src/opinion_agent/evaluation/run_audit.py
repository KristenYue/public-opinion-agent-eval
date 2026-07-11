"""Single-run audit helpers for completed opinion-agent executions."""

from __future__ import annotations

from collections import Counter
from typing import Any

from opinion_agent.evaluation.agent_contracts import evaluate_agent_contract


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _sentiment_summary(result: dict[str, Any]) -> dict[str, Any]:
    sentiment_results = _as_list(result.get("sentiment_results"))
    aggregate = _as_dict(result.get("aggregate_stats"))
    counts = _as_dict(aggregate.get("counts"))
    total = int(aggregate.get("total", len(sentiment_results)) or 0)
    scorable = int(aggregate.get("scorable", 0) or 0)
    unscorable = int(aggregate.get("unscorable", 0) or 0)
    disagreement_rate = _safe_float(aggregate.get("model_disagreement_rate"))

    return {
        "total": total,
        "scorable": scorable,
        "unscorable": unscorable,
        "counts": dict(counts),
        "model_disagreement_count": int(
            aggregate.get("model_disagreement_count", 0) or 0
        ),
        "model_disagreement_rate": disagreement_rate,
    }


def _trace_summary(result: dict[str, Any]) -> dict[str, Any]:
    traces = _as_list(result.get("tool_traces"))
    status_counts = Counter(str(trace.get("status", "unknown")) for trace in traces)
    total_latency_ms = sum(_safe_float(trace.get("duration_ms")) for trace in traces)

    return {
        "nodes": [str(trace.get("node", "")) for trace in traces],
        "status_counts": dict(sorted(status_counts.items())),
        "error_nodes": [
            str(trace.get("node", ""))
            for trace in traces
            if trace.get("status") == "error"
        ],
        "total_latency_ms": round(total_latency_ms, 3),
    }


def _evidence_summary(result: dict[str, Any]) -> dict[str, Any]:
    evidence = _as_list(result.get("retrieved_evidence"))
    report = _as_dict(result.get("analysis_report"))
    references = _as_list(report.get("evidence_references"))
    evidence_ids = [str(item.get("evidence_id", "")) for item in evidence]
    reference_ids = [str(item.get("evidence_id", "")) for item in references]

    return {
        "retrieved_count": len(evidence),
        "referenced_count": len(references),
        "retrieved_ids": evidence_ids,
        "referenced_ids": reference_ids,
        "has_retrieval_evidence": bool(evidence),
    }


def _review_summary(result: dict[str, Any]) -> dict[str, Any]:
    report = _as_dict(result.get("analysis_report"))
    route = _as_dict(result.get("route_decision"))
    review_result = result.get("review_result")

    return {
        "review_status": report.get("review_status", "missing"),
        "needs_review": bool(route.get("needs_review", False)),
        "reasons": _as_list(route.get("reasons")),
        "policy_version": route.get("policy_version"),
        "review_result_present": review_result is not None,
        "disputed_sample_count": len(_as_list(report.get("disputed_sample_ids"))),
    }


def _error_summary(result: dict[str, Any]) -> dict[str, Any]:
    errors = _as_list(result.get("errors"))
    type_counts = Counter(str(error.get("error_type", "unknown")) for error in errors)
    recoverable_count = sum(1 for error in errors if error.get("recoverable") is True)

    return {
        "count": len(errors),
        "recoverable_count": recoverable_count,
        "type_counts": dict(sorted(type_counts.items())),
        "nodes": [str(error.get("node", "")) for error in errors],
    }


def _risk_flags(
    contract: dict[str, Any],
    sentiment: dict[str, Any],
    evidence: dict[str, Any],
    review: dict[str, Any],
    errors: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if not contract.get("passed"):
        flags.append("contract_failed")
    if review["review_status"] == "manual_required":
        flags.append("manual_review_required")
    if review["review_status"] == "llm_failed":
        flags.append("llm_review_failed")
    if review["needs_review"] and not review["review_result_present"]:
        flags.append("review_pending")
    if not evidence["has_retrieval_evidence"]:
        flags.append("no_retrieval_evidence")
    if sentiment["model_disagreement_rate"] >= 0.5:
        flags.append("high_model_disagreement")
    if sentiment["unscorable"] > 0:
        flags.append("unscorable_present")
    if errors["count"] > 0:
        flags.append(
            "recoverable_errors_visible"
            if errors["recoverable_count"] == errors["count"]
            else "non_recoverable_error"
        )
    return flags


def audit_agent_run(
    request: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact reliability audit for one completed agent run."""
    contract = evaluate_agent_contract(request, result)
    sentiment = _sentiment_summary(result)
    traces = _trace_summary(result)
    evidence = _evidence_summary(result)
    review = _review_summary(result)
    errors = _error_summary(result)
    risk_flags = _risk_flags(contract, sentiment, evidence, review, errors)

    tool_count = len(traces["nodes"])
    ok_count = int(traces["status_counts"].get("ok", 0))
    tool_success_rate = ok_count / tool_count if tool_count else 0.0
    contract_score = contract["checks_passed"] / contract["checks_total"]

    status = "pass"
    if not contract["passed"]:
        status = "fail"
    elif risk_flags:
        status = "degraded"

    return {
        "status": status,
        "request_id": request.get("request_id"),
        "event_id": request.get("event_id"),
        "contract": contract,
        "sentiment": sentiment,
        "trajectory": traces,
        "evidence": evidence,
        "review": review,
        "errors": errors,
        "risk_flags": risk_flags,
        "scorecard": {
            "contract_score": round(contract_score, 4),
            "tool_success_rate": round(tool_success_rate, 4),
            "evidence_reference_count": evidence["referenced_count"],
            "total_latency_ms": traces["total_latency_ms"],
        },
    }
