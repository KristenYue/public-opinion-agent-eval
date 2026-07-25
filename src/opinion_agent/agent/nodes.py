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
from .reviewer import review_selection_reason, review_selection_reasons


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
    reasons: list[str] = []
    items = []
    reason_counts: Counter[str] = Counter()
    for result in state.get("sentiment_results", []):
        item_reasons = review_selection_reasons(result)
        reason_counts.update(item_reasons)
        items.append(
            {
                "sample_id": result["sample_id"],
                "needs_review": bool(item_reasons),
                "reasons": item_reasons,
                "baseline_label": result["label"],
                "baseline_confidence": result["confidence"],
                "secondary_label": result.get("secondary_label"),
                "decision_path": "qwen_review" if item_reasons else "fast_path",
            }
        )
    reasons.extend(f"{reason}={count}" for reason, count in sorted(reason_counts.items()))
    decision = {
        "needs_review": any(item["needs_review"] for item in items),
        "reasons": reasons,
        "policy_version": "event_aware_cascade_v1",
        "items": items,
    }
    trace: TraceEvent = {
        "node": "review_router",
        "status": "degraded" if reasons else "ok",
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "details": {
            **decision,
            "confidence_threshold": float(os.getenv("REVIEW_CONFIDENCE_THRESHOLD", "0.65")),
            "short_text_max_chars": int(os.getenv("REVIEW_SHORT_TEXT_MAX_CHARS", "4")),
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
            by_id = {str(item["sample_id"]): item for item in review.get("items", [])}
            reviewed_results: list[SentimentResult] = []
            for result in state.get("sentiment_results", []):
                item = by_id.get(str(result["sample_id"]))
                if item is None:
                    reviewed_results.append(
                        {**result, "review_reasons": [], "decision_path": "fast_path"}
                    )
                    continue
                manual_required = bool(item.get("requires_manual_review"))
                reviewed_results.append(
                    {
                        **result,
                        "original_label": result["label"],
                        "label": item["final_label"],
                        "review_reasons": review_selection_reasons(result),
                        "decision_path": (
                            "manual_required" if manual_required else "qwen_reviewed"
                        ),
                        "qwen_label": item["label"],
                        "qwen_rationale": item["rationale"],
                        "qwen_confidence": item["confidence"],
                    }
                )
            aggregate_update = run_sentiment_aggregator(
                {**state, "sentiment_results": reviewed_results}
            )
            manual_required_count = sum(
                bool(item.get("requires_manual_review"))
                for item in review.get("items", [])
            )
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
                    "manual_required": manual_required_count,
                },
            }
            return {
                "sentiment_results": reviewed_results,
                "aggregate_stats": aggregate_update["aggregate_stats"],
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
        selected_reasons = review_selection_reasons(baseline)
        high_confidence = item["confidence"] == "High"
        applied = (
            item["label"] != baseline_label
            and high_confidence
            and bool(selected_reasons)
        )
        governed_items.append(
            {
                **item,
                "applied": applied,
                "final_label": (
                    item["label"]
                    if high_confidence and selected_reasons
                    else baseline_label
                ),
                "requires_manual_review": bool(selected_reasons) and not high_confidence,
                "decision_reason": (
                    "high_confidence_event_aware_review"
                    if high_confidence and selected_reasons
                    else "reviewer_item_not_selected"
                    if not selected_reasons
                    else "qwen_uncertain_manual_required"
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


def apply_human_review(
    state: AgentState,
    final_labels: dict[str, str],
) -> dict[str, object]:
    """Apply explicit human labels and recompute the final brief audibly."""
    allowed_labels = {"Positive", "Neutral", "Negative", "Unscorable"}
    results = state.get("sentiment_results", [])
    expected_ids = {str(result["sample_id"]) for result in results}
    supplied_ids = {str(sample_id) for sample_id in final_labels}
    if supplied_ids != expected_ids:
        missing = sorted(expected_ids - supplied_ids)
        unknown = sorted(supplied_ids - expected_ids)
        raise ValueError(f"Human review ids do not match; missing={missing}, unknown={unknown}")

    reviewed_results: list[SentimentResult] = []
    review_items = []
    changed = 0
    for result in results:
        sample_id = str(result["sample_id"])
        final_label = str(final_labels[sample_id])
        if final_label not in allowed_labels:
            raise ValueError(f"Unsupported human label for {sample_id}: {final_label}")
        original_label = result["label"]
        changed += final_label != original_label
        reviewed_results.append(
            {
                **result,
                "original_label": original_label,
                "label": final_label,
                "human_reviewed": True,
            }
        )
        review_items.append(
            {
                "sample_id": sample_id,
                "label": final_label,
                "final_label": final_label,
                "rationale": "人工复核确认",
                "confidence": "High",
                "applied": final_label != original_label,
                "decision_reason": "human_adjudication",
            }
        )

    reviewed_state = {**state, "sentiment_results": reviewed_results}
    aggregate_update = run_sentiment_aggregator(reviewed_state)
    review_result: ReviewResult = {
        "items": review_items,  # type: ignore[typeddict-item]
        "summary": f"人工复核完成：{len(review_items)} 条，修正 {changed} 条。",
        "reviewer": "human",
    }
    reviewed_state.update(aggregate_update)
    reviewed_state["review_result"] = review_result
    briefing_update = run_briefing_composer(reviewed_state)
    trace: TraceEvent = {
        "node": "human_review",
        "status": "ok",
        "duration_ms": 0.0,
        "details": {"reviewed": len(review_items), "changed": changed},
    }
    return {
        "sentiment_results": reviewed_results,
        "aggregate_stats": aggregate_update["aggregate_stats"],
        "review_result": review_result,
        **briefing_update,
        "tool_traces": [trace, *briefing_update["tool_traces"]],
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
        if review.get("reviewer") == "human":
            review_status = "human_completed"
        elif any(item.get("requires_manual_review") for item in review.get("items", [])):
            review_status = "manual_required"
        else:
            review_status = "llm_completed"
        attention_level = (
            "Uncertain"
            if review_status == "manual_required"
            else _attention_level(negative_share, disagreement_rate)
        )
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
            (
                "人工复核已完成，但最终业务结论仍需结合组织规则审批。"
                if review_status == "human_completed"
                else "未完成复核的争议评论不得直接用于最终业务结论。"
            ),
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
        fallback_reason = getattr(retriever, "fallback_reason", None)
        trace: TraceEvent = {
            "node": "evidence_retriever",
            "status": "degraded" if fallback_reason or not evidence else "ok",
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "details": {
                "top_k": top_k,
                "returned": len(evidence),
                "same_event_excluded": bool(state.get("event_id")),
                "backend": getattr(
                    retriever,
                    "runtime_backend",
                    type(retriever).__name__,
                ),
                "fallback_reason": fallback_reason,
            },
        }
        return {"retrieved_evidence": evidence, "tool_traces": [trace]}

    return run_evidence_retriever
