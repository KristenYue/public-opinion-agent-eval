from copy import deepcopy
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.run_audit import audit_agent_run  # noqa: E402


def _request() -> dict[str, object]:
    return {
        "request_id": "audit-1",
        "event_id": "current-event",
        "query": "analyze current event",
        "comments": [{"sample_id": "sample-1", "text": "normal length public comment"}],
        "tool_traces": [],
        "errors": [],
    }


def _manual_required_result() -> dict[str, object]:
    return {
        "sentiment_results": [
            {
                "sample_id": "sample-1",
                "text": "normal length public comment",
                "label": "Positive",
                "confidence": 0.82,
                "probabilities": {"Positive": 0.82, "Neutral": 0.1, "Negative": 0.08},
                "source": "stub_model",
                "secondary_label": "Positive",
                "secondary_score": 0.76,
                "models_agree": True,
            }
        ],
        "aggregate_stats": {
            "total": 1,
            "scorable": 1,
            "unscorable": 0,
            "counts": {"Positive": 1, "Neutral": 0, "Negative": 0, "Unscorable": 0},
            "proportions": {"Positive": 1.0, "Neutral": 0.0, "Negative": 0.0},
            "model_disagreement_count": 0,
            "model_disagreement_rate": 0.0,
        },
        "retrieved_evidence": [],
        "route_decision": {
            "needs_review": True,
            "reasons": ["no_retrieval_evidence"],
            "policy_version": "multi_signal_v3",
        },
        "review_result": None,
        "analysis_report": {
            "event_id": "current-event",
            "executive_summary": "Review is required before final judgement.",
            "attention_level": "Uncertain",
            "sentiment_snapshot": {"total": 1, "counts": {"Positive": 1}},
            "risk_signals": ["no_retrieval_evidence"],
            "disputed_sample_ids": [],
            "evidence_references": [],
            "review_status": "manual_required",
            "recommended_actions": ["Run manual review."],
            "limitations": ["No historical evidence was retrieved."],
        },
        "tool_traces": [
            {"node": "sentiment_classifier", "status": "ok", "duration_ms": 1.0, "details": {}},
            {"node": "sentiment_aggregator", "status": "ok", "duration_ms": 1.0, "details": {}},
            {"node": "evidence_retriever", "status": "degraded", "duration_ms": 1.0, "details": {}},
            {"node": "review_router", "status": "degraded", "duration_ms": 1.0, "details": {}},
            {"node": "review_required", "status": "degraded", "duration_ms": 1.0, "details": {}},
            {"node": "briefing_composer", "status": "degraded", "duration_ms": 1.0, "details": {}},
        ],
        "errors": [],
    }


def test_agent_run_audit_summarizes_manual_review_case() -> None:
    audit = audit_agent_run(_request(), _manual_required_result())

    assert audit["status"] == "degraded"
    assert audit["contract"]["passed"] is True
    assert audit["review"]["review_status"] == "manual_required"
    assert audit["risk_flags"] == [
        "manual_review_required",
        "review_pending",
        "no_retrieval_evidence",
    ]
    assert audit["scorecard"]["contract_score"] == 1.0
    assert audit["scorecard"]["tool_success_rate"] == 0.3333


def test_agent_run_audit_exposes_contract_failures() -> None:
    result = deepcopy(_manual_required_result())
    result["analysis_report"]["review_status"] = "not_required"  # type: ignore[index]

    audit = audit_agent_run(_request(), result)

    assert audit["status"] == "fail"
    assert "contract_failed" in audit["risk_flags"]
    assert audit["contract"]["failed_checks"] == ["review_fallback_consistency"]
