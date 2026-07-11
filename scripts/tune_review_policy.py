"""Tune the disagreement-rate review threshold on validation tasks only."""

from pathlib import Path
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "evaluation" / "agent_mvp_metrics.json"
OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "review_policy_tuning.json"
THRESHOLDS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def evaluate(tasks: list[dict[str, object]], threshold: float) -> dict[str, float | int]:
    error_tasks = [task for task in tasks if task["has_label_error"]]
    correct_tasks = [task for task in tasks if not task["has_label_error"]]
    reviewed = [task for task in tasks if float(task["model_disagreement_rate"]) >= threshold]
    captured = [task for task in error_tasks if float(task["model_disagreement_rate"]) >= threshold]
    false_reviews = [task for task in correct_tasks if float(task["model_disagreement_rate"]) >= threshold]
    return {
        "threshold": threshold,
        "review_rate": len(reviewed) / len(tasks) if tasks else 0.0,
        "error_batch_recall": len(captured) / len(error_tasks) if error_tasks else 0.0,
        "false_review_rate": len(false_reviews) / len(correct_tasks) if correct_tasks else 0.0,
        "reviewed_tasks": len(reviewed),
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    validation = [task for task in source["task_results"] if task["split"] == "validation"]
    test = [task for task in source["task_results"] if task["split"] == "test"]
    sweep = [evaluate(validation, threshold) for threshold in THRESHOLDS]
    eligible = [row for row in sweep if row["error_batch_recall"] >= 0.9]
    selected = min(eligible, key=lambda row: row["review_rate"]) if eligible else max(
        sweep, key=lambda row: row["error_batch_recall"]
    )
    report = {
        "selection_rule": "lowest validation review rate while error-batch recall >= 0.90",
        "validation_tasks": len(validation),
        "warning": "Only six validation batches are available; this threshold is provisional.",
        "sweep": sweep,
        "selected_threshold": selected["threshold"],
        "selected_validation_metrics": selected,
        "held_out_test_metrics": evaluate(test, float(selected["threshold"])),
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
