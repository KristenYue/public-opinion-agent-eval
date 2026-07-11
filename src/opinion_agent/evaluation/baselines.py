"""Reproducible evaluation for historical sentiment baselines and routing."""

from collections.abc import Sequence

from sklearn.metrics import accuracy_score, classification_report, confusion_matrix


LABELS = ["Negative", "Neutral", "Positive", "Exclude"]


def normalize_prediction(label: object) -> str:
    value = str(label or "").strip()
    return "Exclude" if value in {"Unscorable", "未知", ""} else value


def evaluate_prediction_column(
    rows: Sequence[dict[str, object]],
    prediction_column: str,
) -> dict[str, object]:
    truth = [str(row["human_label"]) for row in rows]
    predictions = [normalize_prediction(row[prediction_column]) for row in rows]
    report = classification_report(
        truth,
        predictions,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    return {
        "samples": len(rows),
        "accuracy": accuracy_score(truth, predictions),
        "macro_f1": report["macro avg"]["f1-score"],
        "weighted_f1": report["weighted avg"]["f1-score"],
        "per_class": {label: report[label] for label in LABELS},
        "confusion_matrix": {
            "labels": LABELS,
            "values": confusion_matrix(truth, predictions, labels=LABELS).tolist(),
        },
    }


def evaluate_review_policy(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    """Evaluate an agreement gate without pretending review fixes the errors."""
    auto_rows: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []
    baseline_errors = 0
    captured_errors = 0

    for row in rows:
        truth = str(row["human_label"])
        xgb = normalize_prediction(row["xgb_suggestion"])
        snow = normalize_prediction(row["snownlp_suggestion"])
        is_error = xgb != truth
        needs_review = xgb != snow
        if is_error:
            baseline_errors += 1
            if needs_review:
                captured_errors += 1
        (review_rows if needs_review else auto_rows).append(row)

    auto_correct = sum(
        normalize_prediction(row["xgb_suggestion"]) == str(row["human_label"])
        for row in auto_rows
    )
    return {
        "samples": len(rows),
        "policy": "review_when_xgboost_and_snownlp_disagree",
        "auto_count": len(auto_rows),
        "auto_coverage": len(auto_rows) / len(rows) if rows else 0.0,
        "auto_accuracy": auto_correct / len(auto_rows) if auto_rows else 0.0,
        "review_count": len(review_rows),
        "review_rate": len(review_rows) / len(rows) if rows else 0.0,
        "baseline_errors": baseline_errors,
        "captured_errors": captured_errors,
        "error_capture_rate": captured_errors / baseline_errors if baseline_errors else 0.0,
        "note": "Review-path accuracy is not estimated until an actual reviewer is evaluated.",
    }
