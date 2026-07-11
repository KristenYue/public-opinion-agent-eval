"""Pure, testable node factories used by the LangGraph workflow."""

from collections import Counter
from collections.abc import Callable
import os
from time import perf_counter
from typing import Protocol

from opinion_agent.sentiment import SentimentClassifier
from opinion_agent.sentiment.snownlp_baseline import SecondaryPrediction
from opinion_agent.retrieval.retriever import (
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)

from .state import (
    AgentState,
    AggregateStats,
    OpinionBrief,
    ReviewResult,
    SentimentResult,
    TraceEvent,
)
from .reviewer import review_selection_reason


class SecondaryClassifier(Protocol):
    def predict(self, text: str) -> SecondaryPrediction: ...


class PrimaryClassifier(Protocol):
    model_name: str

    def predict(self, text: str): ...


class Reviewer(Protocol):
    def review(self, state: AgentState) -> dict[str, object]: ...


def build_sentiment_classifier_node(
    classifier: PrimaryClassifier,
    secondary_classifier: SecondaryClassifier | None = None,
) -> Callable[[AgentState], dict[str, object]]:
    """Create a node that classifies every scorable comment independently."""

    def run_sentiment_classifier(state: AgentState) -> dict[str, object]:
        started = perf_counter()
        results: list[SentimentResult] = []
        unscorable = 0

        for index, comment in enumerate(state["comments"]):
            sample_id = comment.get("sample_id") or f"comment-{index}"
            text = comment.get("text", "")
            try:
                prediction = classifier.predict(text)
                result: SentimentResult = {
                    "sample_id": sample_id,
                    "text": text,
                    "label": prediction.label,  # type: ignore[typeddict-item]
                    "confidence": prediction.confidence,
                    "probabilities": prediction.probabilities,
                    "source": getattr(classifier, "model_name", "legacy_xgboost"),
                }
                if secondary_classifier is not None:
                    secondary = secondary_classifier.predict(text)
                    result["secondary_label"] = secondary.label  # type: ignore[typeddict-item]
                    result["secondary_score"] = secondary.score
                    result["models_agree"] = secondary.label == prediction.label
                results.append(result)
            except ValueError:
                unscorable += 1
                results.append(
                    {
                        "sample_id": sample_id,
                        "text": text,
                        "label": "Unscorable",
                        "confidence": 0.0,
                        "probabilities": {},
                        "source": "preprocessing_guard",
                    }
                )

        trace: TraceEvent = {
            "node": "sentiment_classifier",
            "status": "degraded" if unscorable else "ok",
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "details": {"comments": len(results), "unscorable": unscorable},
        }
        return {"sentiment_results": results, "tool_traces": [trace]}

    return run_sentiment_classifier


def run_sentiment_aggregator(state: AgentState) -> dict[str, object]:
    """Aggregate model outputs without treating confidence as correctness."""
    started = perf_counter()
    results = state.get("sentiment_results", [])
    counts = Counter(result["label"] for result in results)
    scorable = sum(count for label, count in counts.items() if label != "Unscorable")
    compared = [result for result in results if "models_agree" in result]
    disagreements = sum(not result["models_agree"] for result in compared)
    proportions = {
        label: (count / scorable if scorable else 0.0)
        for label, count in counts.items()
        if label != "Unscorable"
    }
    aggregate: AggregateStats = {
        "total": len(results),
        "scorable": scorable,
        "unscorable": counts.get("Unscorable", 0),
        "counts": dict(counts),
        "proportions": proportions,
        "model_disagreement_count": disagreements,
        "model_disagreement_rate": disagreements / len(compared) if compared else 0.0,
    }
    trace: TraceEvent = {
        "node": "sentiment_aggregator",
        "status": "ok" if scorable else "degraded",
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "details": {"scorable": scorable, "labels": len(proportions)},
    }
    return {"aggregate_stats": aggregate, "tool_traces": [trace]}


def run_review_router(state: AgentState) -> dict[str, object]:
    """Route on observable failure signals rather than XGBoost confidence."""
    started = perf_counter()
    aggregate = state["aggregate_stats"]
    evidence = state.get("retrieved_evidence", [])
    reasons: list[str] = []
    disagreement_threshold = float(os.getenv("REVIEW_DISAGREEMENT_THRESHOLD", "0.0"))
    route_on_no_evidence = os.getenv("REVIEW_ROUTE_ON_NO_EVIDENCE", "1").strip().lower()
    should_route_on_no_evidence = route_on_no_evidence not in {"0", "false", "no"}
    if aggregate["unscorable"]:
        reasons.append(f"unscorable_comments={aggregate['unscorable']}")
    if (
        aggregate["model_disagreement_count"]
        and aggregate["model_disagreement_rate"] >= disagreement_threshold
    ):
        reasons.append(
            f"model_disagreement_rate={aggregate['model_disagreement_rate']:.3f}"
        )
    short_text_count = sum(
        review_selection_reason(result) == "short_text_context_risk"
        for result in state.get("sentiment_results", [])
    )
    if short_text_count:
        reasons.append(f"short_text_context_risk={short_text_count}")
    if should_route_on_no_evidence and not evidence:
        reasons.append("no_retrieval_evidence")
    decision = {
        "needs_review": bool(reasons),
        "reasons": reasons,
        "policy_version": "multi_signal_v3",
    }
    trace: TraceEvent = {
        "node": "review_router",
        "status": "degraded" if reasons else "ok",
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "details": {
            **decision,
            "disagreement_threshold": disagreement_threshold,
            "route_on_no_evidence": should_route_on_no_evidence,
        },
    }
    return {"route_decision": decision, "tool_traces": [trace]}


def mark_review_required(state: AgentState) -> dict[str, object]:
    """Explicit placeholder until the external LLM reviewer is configured."""
    return {
        "review_result": None,
        "final_report": "Review required; no external LLM reviewer is configured.",
        "tool_traces": [
            {
                "node": "review_required",
                "status": "degraded",
                "duration_ms": 0.0,
                "details": {"reasons": state["route_decision"]["reasons"]},
            }
        ],
    }


def build_llm_review_node(reviewer: Reviewer) -> Callable[[AgentState], dict[str, object]]:
    """Create the actual review node; errors remain visible and recoverable."""

    def run_llm_review(state: AgentState) -> dict[str, object]:
        started = perf_counter()
        try:
            review = reviewer.review(state)
            review = apply_reviewer_override_policy(state, review)
            applied = sum(bool(item.get("applied")) for item in review.get("items", []))
            trace: TraceEvent = {
                "node": "llm_review",
                "status": "ok",
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "details": {
                    "reviewed": len(review.get("items", [])),
                    "attempts": review.get("attempts", 1),
                    "usage": review.get("usage", {}),
                    "override_policy": "high_confidence_disagreement_v1",
                    "applied_overrides": applied,
                },
            }
            return {
                "review_result": review,
                "final_report": str(review.get("summary", "Review completed.")),
                "tool_traces": [trace],
            }
        except Exception as exc:
            trace = {
                "node": "llm_review",
                "status": "error",
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "details": {"error_type": type(exc).__name__},
            }
            return {
                "review_result": None,
                "final_report": "LLM review failed; manual review is required.",
                "tool_traces": [trace],
                "errors": [
                    {
                        "node": "llm_review",
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "recoverable": True,
                    }
                ],
            }

    return run_llm_review


def apply_reviewer_override_policy(
    state: AgentState, review: ReviewResult
) -> ReviewResult:
    """Gate LLM label changes; preserve every suggestion for auditability."""
    baseline_by_id = {
        str(result["sample_id"]): result
        for result in state.get("sentiment_results", [])
    }
    governed_items = []
    for item in review.get("items", []):
        baseline = baseline_by_id.get(str(item["sample_id"]))
        if baseline is None:
            governed_items.append(dict(item))
            continue
        baseline_label = baseline["label"]
        disagreement = baseline.get("models_agree") is False
        applied = (
            item["label"] != baseline_label
            and item["confidence"] == "High"
            and disagreement
        )
        governed_items.append(
            {
                **item,
                "applied": applied,
                "final_label": item["label"] if applied else baseline_label,
                "decision_reason": (
                    "high_confidence_model_disagreement"
                    if applied
                    else "reviewer_suggestion_retained_for_audit"
                ),
            }
        )
    return {**review, "items": governed_items}  # type: ignore[return-value]


def mark_baseline_ready(state: AgentState) -> dict[str, object]:
    return {
        "final_report": "Baseline analysis completed without triggering the review gate.",
        "tool_traces": [
            {
                "node": "baseline_ready",
                "status": "ok",
                "duration_ms": 0.0,
                "details": {},
            }
        ],
    }


def run_briefing_composer(state: AgentState) -> dict[str, object]:
    """Compose a stable vertical-domain brief from tools, evidence and review state."""
    started = perf_counter()
    aggregate = state["aggregate_stats"]
    route = state.get(
        "route_decision",
        {"needs_review": False, "reasons": [], "policy_version": "no_retriever"},
    )
    review = state.get("review_result")
    evidence = state.get("retrieved_evidence", [])
    results = state.get("sentiment_results", [])
    negative_share = aggregate["proportions"].get("Negative", 0.0)
    disagreement_rate = aggregate["model_disagreement_rate"]
    disputed_ids = [
        result["sample_id"]
        for result in results
        if review_selection_reason(result) is not None
    ]

    if route["needs_review"] and review is None:
        review_status = "llm_failed" if state.get("errors") else "manual_required"
        attention_level = "Uncertain"
    elif review is not None:
        review_status = "llm_completed"
        attention_level = _attention_level(negative_share, disagreement_rate)
    else:
        review_status = "not_required"
        attention_level = _attention_level(negative_share, disagreement_rate)

    risk_signals: list[str] = []
    if negative_share:
        risk_signals.append(f"negative_share={negative_share:.3f}")
    if disagreement_rate:
        risk_signals.append(f"model_disagreement_rate={disagreement_rate:.3f}")
    risk_signals.extend(route["reasons"])
    if not evidence:
        risk_signals.append("no_accepted_historical_evidence")
    risk_signals = list(dict.fromkeys(risk_signals))

    actions: list[str] = []
    if review_status in {"manual_required", "llm_failed"}:
        actions.append("人工复核争议评论并记录最终依据")
    if negative_share >= 0.25:
        actions.append("持续跟踪负面议题及其传播变化")
    if not evidence:
        actions.append("补充同类历史事件卡片后重新检索")
    if not actions:
        actions.append("保持常规监测并关注情绪分布变化")

    summary = (
        f"事件 {state['event_id']} 共分析 {aggregate['total']} 条评论；"
        f"负面占比 {negative_share:.1%}，模型分歧率 {disagreement_rate:.1%}；"
        f"当前关注级别为 {attention_level}，复核状态为 {review_status}。"
    )
    report: OpinionBrief = {
        "event_id": state["event_id"],
        "executive_summary": summary,
        "attention_level": attention_level,
        "sentiment_snapshot": {
            "total": aggregate["total"],
            "scorable": aggregate["scorable"],
            "counts": aggregate["counts"],
            "proportions": aggregate["proportions"],
            "model_disagreement_rate": disagreement_rate,
        },
        "risk_signals": risk_signals,
        "disputed_sample_ids": disputed_ids,
        "evidence_references": [
            {
                "evidence_id": item["evidence_id"],
                "event_id": item["event_id"],
                "source_url": item["source_url"],
                "score": item["score"],
            }
            for item in evidence
        ],
        "review_status": review_status,
        "recommended_actions": actions,
        "limitations": [
            "情绪模型输出仅作为研判信号，不等同于人工真值。",
            "历史事件检索结果用于提供上下文，不证明因果关系。",
            "未完成复核的争议评论不得直接用于最终业务结论。",
        ],
    }
    trace: TraceEvent = {
        "node": "briefing_composer",
        "status": "degraded" if review_status in {"manual_required", "llm_failed"} else "ok",
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "details": {
            "attention_level": attention_level,
            "review_status": review_status,
            "evidence_references": len(evidence),
            "disputed_comments": len(disputed_ids),
        },
    }
    return {
        "analysis_report": report,
        "risk_assessment": {
            "attention_level": attention_level,
            "factors": risk_signals,
            "limitations": report["limitations"],
        },
        "final_report": summary,
        "tool_traces": [trace],
    }


def _attention_level(negative_share: float, disagreement_rate: float) -> str:
    if negative_share >= 0.5:
        return "High"
    if negative_share >= 0.25 or disagreement_rate >= 0.4:
        return "Medium"
    return "Low"


def build_evidence_retriever_node(
    retriever: TfidfEventRetriever | SemanticEventRetriever | HybridEventRetriever,
    top_k: int = 3,
) -> Callable[[AgentState], dict[str, object]]:
    """Create a node that retrieves prior events and blocks same-event leakage."""

    def run_evidence_retriever(state: AgentState) -> dict[str, object]:
        started = perf_counter()
        comment_context = "\n".join(comment.get("text", "") for comment in state["comments"][:10])
        query = f"{state['query']}\n{comment_context}".strip()
        evidence = retriever.retrieve(
            query=query,
            top_k=top_k,
            exclude_event_id=state.get("event_id"),
        )
        trace: TraceEvent = {
            "node": "evidence_retriever",
            "status": "ok" if evidence else "degraded",
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "details": {
                "top_k": top_k,
                "returned": len(evidence),
                "same_event_excluded": bool(state.get("event_id")),
            },
        }
        return {"retrieved_evidence": evidence, "tool_traces": [trace]}

    return run_evidence_retriever
