from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.baselines import (  # noqa: E402
    evaluate_prediction_column,
    evaluate_review_policy,
    normalize_prediction,
)


def test_unscorable_maps_to_exclude_for_four_class_evaluation() -> None:
    assert normalize_prediction("Unscorable") == "Exclude"


def test_review_policy_reports_coverage_and_error_capture() -> None:
    rows = [
        {"human_label": "Positive", "xgb_suggestion": "Positive", "snownlp_suggestion": "Positive"},
        {"human_label": "Negative", "xgb_suggestion": "Positive", "snownlp_suggestion": "Negative"},
    ]
    result = evaluate_review_policy(rows)

    assert result["auto_coverage"] == 0.5
    assert result["auto_accuracy"] == 1.0
    assert result["error_capture_rate"] == 1.0


def test_prediction_metrics_include_all_four_labels() -> None:
    rows = [
        {"human_label": "Exclude", "xgb_suggestion": "Unscorable"},
        {"human_label": "Positive", "xgb_suggestion": "Positive"},
    ]
    result = evaluate_prediction_column(rows, "xgb_suggestion")

    assert result["accuracy"] == 1.0
    assert result["confusion_matrix"]["labels"] == [
        "Negative",
        "Neutral",
        "Positive",
        "Exclude",
    ]
