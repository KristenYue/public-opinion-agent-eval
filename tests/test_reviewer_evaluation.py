from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import run_reviewer_benchmark  # noqa: E402


class ExpectedReviewer:
    def __init__(self, expected: dict[str, str]) -> None:
        self.expected = expected

    def review(self, state):
        return {
            "items": [
                {
                    "sample_id": result["sample_id"],
                    "label": self.expected[result["sample_id"]],
                    "rationale": "Context-supported decision.",
                    "confidence": "High",
                }
                for result in state["sentiment_results"]
            ],
            "summary": "done",
            "reviewer": "expected-reviewer",
        }


def test_reviewer_benchmark_scores_contract_and_corrections() -> None:
    cases = [
        {
            "sample_id": "a",
            "event_id": "event",
            "text": "bad",
            "context": "context",
            "source_url": "",
            "xgb_label": "Neutral",
            "xgb_confidence": 0.6,
            "secondary_label": "Negative",
            "secondary_score": 0.2,
            "expected_label": "Negative",
            "selected_for_review": True,
        },
        {
            "sample_id": "b",
            "event_id": "event",
            "text": "ok",
            "context": "context",
            "source_url": "",
            "xgb_label": "Positive",
            "xgb_confidence": 0.7,
            "secondary_label": "Neutral",
            "secondary_score": 0.5,
            "expected_label": "Positive",
            "selected_for_review": True,
        },
    ]

    metrics, responses = run_reviewer_benchmark(
        cases,
        ExpectedReviewer({"a": "Negative", "b": "Positive"}),
        batch_size=2,
    )

    assert len(responses) == 2
    assert metrics["structured_batch_success_rate"] == 1.0
    assert metrics["item_coverage"] == 1.0
    assert metrics["label_accuracy_on_returned_items"] == 1.0
    assert metrics["baseline_error_correction_rate"] == 1.0
    assert metrics["rationale_coverage"] == 1.0
    assert metrics["http_attempts"] == 1
    assert metrics["usage"]["total_tokens"] == 0
