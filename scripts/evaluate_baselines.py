"""Evaluate provisional human labels with leakage-safe event splits."""

from pathlib import Path
from collections import Counter
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import (  # noqa: E402
    adjudication_reasons,
    evaluate_prediction_column,
    evaluate_review_policy,
)


VALIDATION_EVENTS = {"五一反向旅游", "延迟法定退休年龄改革"}
TEST_EVENTS = {"雷军", "关税"}


def split_name(event_id: str) -> str:
    if event_id in TEST_EVENTS:
        return "test"
    if event_id in VALIDATION_EVENTS:
        return "validation"
    return "train"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "annotations_provisional.jsonl",
    )
    parser.add_argument(
        "--cases-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "evaluation_cases.jsonl",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "baseline_metrics.json",
    )
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.source.read_text(encoding="utf-8").split("\n")
        if line
    ]

    cases: list[dict[str, object]] = []
    for row in rows:
        cases.append(
            {
                **row,
                "split": split_name(str(row["event_id"])),
                "requires_adjudication": bool(adjudication_reasons(row)),
            }
        )

    args.cases_output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in cases) + "\n",
        encoding="utf-8",
    )
    grouped = {
        split: [row for row in cases if row["split"] == split]
        for split in ("train", "validation", "test")
    }
    truth_status_counts = Counter(str(row.get("truth_status", "unknown")) for row in rows)
    adjudication_status_counts = Counter(
        str(row.get("adjudication_status", "not_recorded")) for row in rows
    )
    adjudicated = adjudication_status_counts.get("adjudicated", 0)
    metrics = {
        "source": str(args.source),
        "truth_status": (
            "mixed_partial_second_pass"
            if len(truth_status_counts) > 1
            else next(iter(truth_status_counts), "unknown")
        ),
        "truth_status_counts": dict(sorted(truth_status_counts.items())),
        "adjudication_status_counts": dict(sorted(adjudication_status_counts.items())),
        "adjudication_coverage": adjudicated / len(rows) if rows else 0.0,
        "limitations": [
            "Only rows marked second_pass_adjudicated have completed the focused repeat review.",
            "Remaining rows retain provisional single-annotator labels.",
            "Test-set estimates have wide uncertainty because only 38 samples are available.",
            "The routing metric measures error capture, not post-review task accuracy.",
        ],
        "split_counts": {split: len(items) for split, items in grouped.items()},
        "adjudication_candidates": sum(bool(row["requires_adjudication"]) for row in cases),
        "splits": {
            split: {
                "xgboost": evaluate_prediction_column(items, "xgb_suggestion"),
                "snownlp": evaluate_prediction_column(items, "snownlp_suggestion"),
                "review_policy": evaluate_review_policy(items),
            }
            for split, items in grouped.items()
        },
    }
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
