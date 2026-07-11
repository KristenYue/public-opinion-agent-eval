from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.nodes import (  # noqa: E402
    build_sentiment_classifier_node,
    run_sentiment_aggregator,
    run_review_router,
)
from opinion_agent.sentiment.classifier import Prediction  # noqa: E402
from opinion_agent.sentiment.snownlp_baseline import SecondaryPrediction  # noqa: E402


class StubClassifier:
    model_name = "stub_classifier"

    def predict(self, text: str) -> Prediction:
        if not text.strip():
            raise ValueError("empty")
        label = "Negative" if "差" in text else "Positive"
        return Prediction(label, 0.8, {label: 0.8}, text)


class StubSecondaryClassifier:
    def predict(self, text: str) -> SecondaryPrediction:
        return SecondaryPrediction("Neutral", 0.5)


def test_sentiment_nodes_preserve_unscorable_samples() -> None:
    state = {
        "request_id": "r1",
        "event_id": "event-a",
        "query": "分析事件",
        "comments": [
            {"sample_id": "a", "text": "很好"},
            {"sample_id": "b", "text": "太差了"},
            {"sample_id": "c", "text": ""},
        ],
        "tool_traces": [],
        "errors": [],
    }
    classify = build_sentiment_classifier_node(StubClassifier())  # type: ignore[arg-type]
    classified = classify(state)
    aggregate = run_sentiment_aggregator({**state, **classified})

    assert [row["label"] for row in classified["sentiment_results"]] == [
        "Positive",
        "Negative",
        "Unscorable",
    ]
    assert classified["sentiment_results"][0]["source"] == "stub_classifier"
    assert aggregate["aggregate_stats"]["scorable"] == 2
    assert aggregate["aggregate_stats"]["unscorable"] == 1
    assert aggregate["aggregate_stats"]["model_disagreement_count"] == 0


def test_secondary_signal_records_disagreement() -> None:
    state = {
        "request_id": "r2",
        "event_id": "event-b",
        "query": "分析事件",
        "comments": [{"sample_id": "a", "text": "很好"}],
        "tool_traces": [],
        "errors": [],
    }
    classify = build_sentiment_classifier_node(  # type: ignore[arg-type]
        StubClassifier(), StubSecondaryClassifier()
    )
    classified = classify(state)
    aggregate = run_sentiment_aggregator({**state, **classified})

    assert classified["sentiment_results"][0]["models_agree"] is False
    assert aggregate["aggregate_stats"]["model_disagreement_rate"] == 1.0


def test_review_router_routes_short_context_dependent_comment() -> None:
    result = run_review_router(
        {
            "aggregate_stats": {
                "total": 1,
                "scorable": 1,
                "unscorable": 0,
                "counts": {"Positive": 1},
                "proportions": {"Positive": 1.0},
                "model_disagreement_count": 0,
                "model_disagreement_rate": 0.0,
            },
            "sentiment_results": [
                {
                    "sample_id": "a",
                    "text": "好听",
                    "label": "Positive",
                    "confidence": 0.8,
                    "probabilities": {"Positive": 0.8},
                    "source": "legacy_xgboost",
                    "secondary_label": "Positive",
                    "secondary_score": 0.8,
                    "models_agree": True,
                }
            ],
            "retrieved_evidence": [{"evidence_id": "e"}],
        }
    )

    assert result["route_decision"]["needs_review"] is True
    assert result["route_decision"]["policy_version"] == "multi_signal_v3"
    assert "short_text_context_risk=1" in result["route_decision"]["reasons"]


def test_review_router_threshold_can_release_low_disagreement_batch(monkeypatch) -> None:
    monkeypatch.setenv("REVIEW_DISAGREEMENT_THRESHOLD", "0.8")
    monkeypatch.setenv("REVIEW_ROUTE_ON_NO_EVIDENCE", "0")

    result = run_review_router(
        {
            "aggregate_stats": {
                "total": 10,
                "scorable": 10,
                "unscorable": 0,
                "counts": {"Positive": 10},
                "proportions": {"Positive": 1.0},
                "model_disagreement_count": 3,
                "model_disagreement_rate": 0.3,
            },
            "sentiment_results": [
                {
                    "sample_id": "a",
                    "text": "normal length comment",
                    "label": "Positive",
                    "confidence": 0.8,
                    "probabilities": {"Positive": 0.8},
                    "source": "legacy_xgboost",
                    "secondary_label": "Neutral",
                    "secondary_score": 0.5,
                    "models_agree": False,
                }
            ],
            "retrieved_evidence": [],
        }
    )

    assert result["route_decision"]["needs_review"] is False
    assert result["tool_traces"][0]["details"]["disagreement_threshold"] == 0.8
