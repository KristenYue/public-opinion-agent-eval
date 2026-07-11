"""Build a reproducible reliability report for the focused-adjudication evaluation set."""

from collections import Counter
from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import bootstrap_classification_metrics  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "evaluation_cases_partial_adjudication.jsonl",
    )
    parser.add_argument(
        "--provisional-metrics",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "baseline_metrics.json",
    )
    parser.add_argument(
        "--adjudicated-metrics",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "baseline_metrics_partial_adjudication.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "evaluation_reliability.json",
    )
    parser.add_argument("--iterations", type=int, default=5000)
    args = parser.parse_args()

    rows = read_jsonl(args.cases)
    test_rows = [row for row in rows if row["split"] == "test"]
    provisional = json.loads(args.provisional_metrics.read_text(encoding="utf-8"))
    adjudicated = json.loads(args.adjudicated_metrics.read_text(encoding="utf-8"))
    adjudicated_rows = [row for row in rows if row.get("adjudication_status") == "adjudicated"]
    changed_rows = [row for row in adjudicated_rows if row.get("adjudication_changed_label")]

    sensitivity: dict[str, object] = {}
    for model in ("xgboost", "snownlp"):
        before = provisional["splits"]["test"][model]
        after = adjudicated["splits"]["test"][model]
        sensitivity[model] = {
            "provisional_accuracy": before["accuracy"],
            "focused_adjudication_accuracy": after["accuracy"],
            "accuracy_delta": after["accuracy"] - before["accuracy"],
            "provisional_macro_f1": before["macro_f1"],
            "focused_adjudication_macro_f1": after["macro_f1"],
            "macro_f1_delta": after["macro_f1"] - before["macro_f1"],
        }

    report = {
        "status": "focused_second_pass_complete_not_independent_gold_standard",
        "samples": len(rows),
        "test_samples": len(test_rows),
        "test_events": len({str(row["event_id"]) for row in test_rows}),
        "adjudication": {
            "focused_candidates": 107,
            "completed": len(adjudicated_rows),
            "candidate_completion_rate": len(adjudicated_rows) / 107,
            "dataset_coverage": len(adjudicated_rows) / len(rows),
            "label_changes": len(changed_rows),
            "label_change_rate_within_adjudicated": (
                len(changed_rows) / len(adjudicated_rows) if adjudicated_rows else 0.0
            ),
            "completed_by_split": dict(
                sorted(Counter(str(row["split"]) for row in adjudicated_rows).items())
            ),
            "changes_by_split": dict(
                sorted(Counter(str(row["split"]) for row in changed_rows).items())
            ),
        },
        "test_uncertainty": {
            "xgboost": bootstrap_classification_metrics(
                test_rows, "xgb_suggestion", iterations=args.iterations
            ),
            "snownlp": bootstrap_classification_metrics(
                test_rows, "snownlp_suggestion", iterations=args.iterations
            ),
        },
        "label_sensitivity": sensitivity,
        "limitations": [
            "The focused second pass reviewed 107 high-risk rows, not all 242 rows.",
            "The repeat review is not an independent second-annotator agreement study.",
            "The test split has only 38 comments from two events.",
            "Bootstrap intervals resample rows and do not measure unseen-event uncertainty.",
        ],
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
