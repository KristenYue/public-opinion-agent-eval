from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.nodes import (  # noqa: E402
    apply_reviewer_override_policy,
    build_llm_review_node,
)
from opinion_agent.agent.reviewer import review_selection_reason  # noqa: E402


class FakeReviewer:
    def review(self, state):
        return {
            "items": [
                {
                    "sample_id": "a",
                    "label": "Negative",
                    "rationale": "包含明确批评",
                    "confidence": "High",
                }
            ],
            "summary": "复核完成",
            "reviewer": "fake-reviewer",
        }


def test_llm_review_node_returns_structured_result() -> None:
    node = build_llm_review_node(FakeReviewer())
    result = node({"sentiment_results": [], "tool_traces": [], "errors": []})

    assert result["review_result"]["items"][0]["label"] == "Negative"
    assert result["final_report"] == "复核完成"


def test_short_agreeing_comment_is_selected_for_context_review() -> None:
    assert review_selection_reason(
        {"label": "Positive", "models_agree": True, "text": "好听"}
    ) == "short_text_context_risk"
    assert review_selection_reason(
        {"label": "Positive", "models_agree": True, "text": "这场演出真的非常好听"}
    ) is None


def test_override_policy_applies_only_high_confidence_disagreement() -> None:
    state = {
        "sentiment_results": [
            {
                "sample_id": "a",
                "text": "成本明显增加",
                "label": "Neutral",
                "confidence": 0.6,
                "models_agree": False,
            },
            {
                "sample_id": "b",
                "text": "这是正常长度的客观信息",
                "label": "Neutral",
                "confidence": 0.9,
                "models_agree": True,
            },
        ]
    }
    review = {
        "items": [
            {"sample_id": "a", "label": "Negative", "rationale": "x", "confidence": "High"},
            {"sample_id": "b", "label": "Positive", "rationale": "y", "confidence": "High"},
        ],
        "summary": "done",
        "reviewer": "fake",
    }

    governed = apply_reviewer_override_policy(state, review)  # type: ignore[arg-type]

    assert governed["items"][0]["applied"] is True
    assert governed["items"][0]["final_label"] == "Negative"
    assert governed["items"][1]["applied"] is False
    assert governed["items"][1]["final_label"] == "Neutral"


def test_llm_review_updates_final_sentiment_and_aggregate() -> None:
    node = build_llm_review_node(FakeReviewer())
    state = {
        "sentiment_results": [
            {
                "sample_id": "a",
                "text": "普通消费者承担更高成本",
                "label": "Neutral",
                "confidence": 0.55,
                "probabilities": {"Neutral": 0.55},
                "source": "legacy_xgboost",
                "secondary_label": "Negative",
                "secondary_score": 0.2,
                "models_agree": False,
            }
        ],
        "tool_traces": [],
        "errors": [],
    }

    result = node(state)  # type: ignore[arg-type]

    assert result["sentiment_results"][0]["original_label"] == "Neutral"
    assert result["sentiment_results"][0]["label"] == "Negative"
    assert result["sentiment_results"][0]["decision_path"] == "qwen_reviewed"
    assert result["aggregate_stats"]["counts"] == {"Negative": 1}
