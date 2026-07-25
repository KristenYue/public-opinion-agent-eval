from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.nodes import (  # noqa: E402
    build_llm_review_node,
    build_sentiment_classifier_node,
    run_review_router,
    run_sentiment_aggregator,
)
from opinion_agent.sentiment.classifier import Prediction  # noqa: E402
from opinion_agent.sentiment.snownlp_baseline import SecondaryPrediction  # noqa: E402


DEMO_EXPECTED = {
    "普通消费者最后还是要承担更高成本": "Negative",
    "先看看后续具体实施细则": "Neutral",
    "又变了": "Negative",
    "这项调整对国内企业可能是机会": "Positive",
    "政策一天一个样，完全看不懂": "Negative",
}


class NeutralBaseline:
    model_name = "legacy_xgboost"

    def predict(self, text: str) -> Prediction:
        confidence = 0.48 if "看不懂" in text else 0.75
        return Prediction("Neutral", confidence, {"Neutral": confidence}, text)


class DemoSecondary:
    def predict(self, text: str) -> SecondaryPrediction:
        labels = {
            "普通消费者最后还是要承担更高成本": "Negative",
            "先看看后续具体实施细则": "Positive",
            "又变了": "Neutral",
            "这项调整对国内企业可能是机会": "Positive",
            "政策一天一个样，完全看不懂": "Neutral",
        }
        return SecondaryPrediction(labels[text], 0.8)


class ContextAwareQwenStub:
    """Contract stub only; it does not claim live-Qwen quality."""

    def review(self, state):
        assert all(comment["context"] for comment in state["comments"])
        return {
            "items": [
                {
                    "sample_id": result["sample_id"],
                    "label": DEMO_EXPECTED[result["text"]],
                    "rationale": "结合事件背景进行目标感知判断",
                    "confidence": "High",
                }
                for result in state["sentiment_results"]
            ],
            "summary": "事件感知复核完成",
            "reviewer": "qwen-contract-stub",
        }


def test_five_demo_failures_are_escalated_with_context_and_written_back() -> None:
    context = "某项关税政策频繁调整，引发消费者成本、企业机会和稳定性讨论。"
    state = {
        "request_id": "demo-cascade",
        "event_id": "关税政策调整",
        "query": "判断评论对该政策调整的态度",
        "comments": [
            {"sample_id": f"c{index}", "text": text, "context": context}
            for index, text in enumerate(DEMO_EXPECTED, start=1)
        ],
        "tool_traces": [],
        "errors": [],
    }
    classified = build_sentiment_classifier_node(
        NeutralBaseline(), DemoSecondary()
    )(state)  # type: ignore[arg-type]
    staged = {**state, **classified}
    staged.update(run_sentiment_aggregator(staged))
    route = run_review_router(staged)
    staged.update(route)

    assert route["route_decision"]["needs_review"] is True
    assert all(item["needs_review"] for item in route["route_decision"]["items"])

    reviewed = build_llm_review_node(ContextAwareQwenStub())(staged)  # type: ignore[arg-type]

    assert [row["label"] for row in reviewed["sentiment_results"]] == list(
        DEMO_EXPECTED.values()
    )
    assert all(
        row["decision_path"] == "qwen_reviewed"
        for row in reviewed["sentiment_results"]
    )


def test_medium_qwen_confidence_requires_human_instead_of_overriding() -> None:
    class UncertainReviewer:
        def review(self, state):
            return {
                "items": [
                    {
                        "sample_id": "c1",
                        "label": "Negative",
                        "rationale": "上下文仍不足",
                        "confidence": "Medium",
                    }
                ],
                "summary": "需要人工确认",
                "reviewer": "qwen-contract-stub",
            }

    state = {
        "sentiment_results": [
            {
                "sample_id": "c1",
                "text": "又变了",
                "label": "Neutral",
                "confidence": 0.7,
                "probabilities": {"Neutral": 0.7},
                "source": "legacy_xgboost",
                "secondary_label": "Neutral",
                "secondary_score": 0.5,
                "models_agree": True,
            }
        ],
        "tool_traces": [],
        "errors": [],
    }
    result = build_llm_review_node(UncertainReviewer())(state)  # type: ignore[arg-type]

    assert result["sentiment_results"][0]["label"] == "Neutral"
    assert result["sentiment_results"][0]["decision_path"] == "manual_required"
    assert result["review_result"]["items"][0]["requires_manual_review"] is True
