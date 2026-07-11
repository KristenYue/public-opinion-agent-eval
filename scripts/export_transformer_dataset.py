"""Export event-split sentiment data for Transformer fine-tuning.

The script does not train a model.  It turns the existing adjudicated/provisional
evaluation cases into simple JSONL files that can be consumed by Hugging Face
`datasets`, ModelScope, or a custom PyTorch training loop.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import csv
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


LABELS = ["Negative", "Neutral", "Positive", "Unscorable"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
HUMAN_TO_TRAINING_LABEL = {
    "Negative": "Negative",
    "Neutral": "Neutral",
    "Positive": "Positive",
    "Exclude": "Unscorable",
    "Unscorable": "Unscorable",
}


def load_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    buffer = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() and not buffer:
            continue
        buffer = f"{buffer}\n{line}" if buffer else line
        try:
            rows.append(json.loads(buffer))
            buffer = ""
        except json.JSONDecodeError:
            continue
    if buffer:
        raise ValueError(f"Could not parse trailing JSON object from {path}")
    return rows


def normalize_row(row: dict[str, object]) -> dict[str, object] | None:
    raw_label = str(row.get("human_label", "")).strip()
    label = HUMAN_TO_TRAINING_LABEL.get(raw_label)
    text = str(row.get("content", "")).strip()
    split = str(row.get("split", "")).strip()
    if not label or not text or split not in {"train", "validation", "test"}:
        return None

    return {
        "sample_id": str(row.get("sample_id", "")),
        "event_id": str(row.get("event_id", "")),
        "text": text,
        "post_text": str(row.get("post_text", "")),
        "label": label,
        "label_id": LABEL_TO_ID[label],
        "split": split,
        "truth_status": str(row.get("truth_status", "unknown")),
        "adjudication_status": str(row.get("adjudication_status", "unknown")),
        "source_file": "evaluation_cases_partial_adjudication.jsonl",
    }


def normalize_legacy_csv_row(
    row: dict[str, str],
    split: str,
    index: int,
) -> dict[str, object] | None:
    raw_label = row.get("sentiment", "").strip()
    label = HUMAN_TO_TRAINING_LABEL.get(raw_label)
    text = row.get("content", "").strip()
    if not label or not text:
        return None
    sample_id = row.get("comment_id", "").strip() or f"{split}-{index}"
    return {
        "sample_id": sample_id,
        "event_id": "legacy_split_unknown_event",
        "text": text,
        "post_text": "",
        "label": label,
        "label_id": LABEL_TO_ID[label],
        "split": split,
        "truth_status": "legacy_split_label",
        "adjudication_status": "not_applicable",
        "source_file": f"legacy_split/{split}.csv",
    }


def load_legacy_csv(path: Path, split: str) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            row
            for index, source_row in enumerate(reader)
            if (row := normalize_legacy_csv_row(source_row, split, index))
        ]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Optional evaluation JSONL source. If omitted, legacy CSV split is used.",
    )
    parser.add_argument(
        "--legacy-train-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "legacy_split" / "训练集.csv",
    )
    parser.add_argument(
        "--legacy-test-csv",
        type=Path,
        default=PROJECT_ROOT / "data" / "legacy_split" / "测试集.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "modeling" / "transformer_sentiment",
    )
    parser.add_argument(
        "--adjudicated-only",
        action="store_true",
        help="Export only rows that completed second-pass adjudication.",
    )
    args = parser.parse_args()

    source_description: str
    if args.source is not None:
        source_rows = load_jsonl(args.source)
        normalized = [row for row in (normalize_row(row) for row in source_rows) if row]
        if args.adjudicated_only:
            normalized = [
                row
                for row in normalized
                if row.get("adjudication_status") == "adjudicated"
            ]
        source_description = str(args.source)
    else:
        train_rows = load_legacy_csv(args.legacy_train_csv, "train")
        test_rows = load_legacy_csv(args.legacy_test_csv, "test")
        validation_rows = [
            {**row, "split": "validation"}
            for index, row in enumerate(train_rows)
            if index % 5 == 0
        ]
        train_rows = [row for index, row in enumerate(train_rows) if index % 5 != 0]
        normalized = train_rows + validation_rows + test_rows
        source_description = f"{args.legacy_train_csv}; {args.legacy_test_csv}"

    grouped = {
        split: [row for row in normalized if row["split"] == split]
        for split in ("train", "validation", "test")
    }
    for split, rows in grouped.items():
        write_jsonl(args.output_dir / f"{split}.jsonl", rows)

    report = {
        "source": source_description,
        "output_dir": str(args.output_dir),
        "labels": LABELS,
        "label_to_id": LABEL_TO_ID,
        "adjudicated_only": args.adjudicated_only,
        "total": len(normalized),
        "split_counts": {split: len(rows) for split, rows in grouped.items()},
        "label_counts": {
            split: dict(sorted(Counter(str(row["label"]) for row in rows).items()))
            for split, rows in grouped.items()
        },
        "truth_status_counts": dict(
            sorted(Counter(str(row["truth_status"]) for row in normalized).items())
        ),
        "limitations": [
            "This export is for the first supervised classifier experiment, not the final gold-standard annotation.",
            "When using legacy CSV mode, validation is carved from the legacy training CSV and may not be event-isolated.",
            "The partially adjudicated evaluation JSONL should be repaired or regenerated before final model claims.",
            "Rows not marked second_pass_adjudicated are still provisional labels when evaluation JSONL mode is used.",
        ],
    }
    report_path = args.output_dir / "dataset_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
