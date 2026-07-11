from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.nodes import run_briefing_composer  # noqa: E402


def test_briefing_exposes_manual_review_and_grounded_actions() -> None:
    result = run_briefing_composer(
        {
            "request_id": "r1",
            "event_id": "event-a",
            "query": "analyze",
            "comments": [{"sample_id": "a", "text": "bad"}],
            "sentiment_results": [
                {
                    "sample_id": "a",
                    "text": "bad",
                    "label": "Negative",
                    "confidence": 0.7,
                    "probabilities": {"Negative": 0.7},
                    "source": "legacy_xgboost",
                    "secondary_label": "Neutral",
                    "secondary_score": 0.5,
                    "models_agree": False,
                }
            ],
            "aggregate_stats": {
                "total": 1,
                "scorable": 1,
                "unscorable": 0,
                "counts": {"Negative": 1},
                "proportions": {"Negative": 1.0},
                "model_disagreement_count": 1,
                "model_disagreement_rate": 1.0,
            },
            "retrieved_evidence": [],
            "route_decision": {
                "needs_review": True,
                "reasons": ["model_disagreement_rate=1.000"],
                "policy_version": "multi_signal_v1",
            },
            "review_result": None,
            "tool_traces": [],
            "errors": [],
        }
    )

    report = result["analysis_report"]
    assert report["review_status"] == "manual_required"
    assert report["attention_level"] == "Uncertain"
    assert report["disputed_sample_ids"] == ["a"]
    assert "人工复核争议评论并记录最终依据" in report["recommended_actions"]
    assert result["tool_traces"][0]["node"] == "briefing_composer"
