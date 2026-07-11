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
            {"sample_id": "a", "label": "Neutral", "models_agree": False},
            {"sample_id": "b", "label": "Neutral", "models_agree": True},
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
