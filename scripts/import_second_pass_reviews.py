"""Validate and merge the 38-row independent second-pass review.

The input is a JSON array exported from the review workbook.  The script is
fail-closed: it writes nothing unless every currently pending sample has one
valid, matching response.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DEFAULT_MODEL_ROOT = WORKSPACE_ROOT / "本科毕设_情感分析_恢复版"
VALID_LABELS = {"Negative", "Neutral", "Positive", "Exclude"}
VALID_CONFIDENCES = {"High", "Medium", "Low"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_and_merge(
    reviews: list[dict[str, Any]],
    responses: list[dict[str, Any]],
    *,
    expected_sample_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pending = {
        str(row["sample_id"]): row
        for row in reviews
        if bool(row.get("needs_review"))
        and (
            expected_sample_ids is None
            or str(row["sample_id"]) in expected_sample_ids
        )
    }
    seen: set[str] = set()
    errors: list[dict[str, Any]] = []
    valid_by_id: dict[str, dict[str, Any]] = {}

    for response in responses:
        sample_id = str(response.get("sample_id", "")).strip()
        row_number = response.get("row_number")
        row_errors: list[str] = []
        if not sample_id:
            row_errors.append("missing sample_id")
        elif sample_id in seen:
            row_errors.append("duplicate sample_id")
        elif sample_id not in pending:
            row_errors.append("sample is not in the pending second-pass set")
        else:
            first_label = str(response.get("first_label", "")).strip()
            if first_label != str(pending[sample_id].get("human_label", "")).strip():
                row_errors.append("first_label does not match the stored first pass")

        label = str(response.get("second_label", "")).strip()
        confidence = str(response.get("second_confidence", "")).strip()
        rationale = str(response.get("second_rationale", "")).strip()
        if label not in VALID_LABELS:
            row_errors.append(f"invalid second_label: {label!r}")
        if confidence not in VALID_CONFIDENCES:
            row_errors.append(f"invalid second_confidence: {confidence!r}")
        if not rationale:
            row_errors.append("missing second_rationale")

        if sample_id:
            seen.add(sample_id)
        if row_errors:
            errors.append(
                {
                    "row_number": row_number,
                    "sample_id": sample_id,
                    "errors": row_errors,
                }
            )
        else:
            valid_by_id[sample_id] = response

    missing_ids = sorted(set(pending) - seen)
    if missing_ids:
        errors.append(
            {
                "row_number": None,
                "sample_id": None,
                "errors": [f"missing {len(missing_ids)} pending sample(s)"],
                "missing_sample_ids": missing_ids,
            }
        )

    report: dict[str, Any] = {
        "pending_expected": len(pending),
        "responses_received": len(responses),
        "valid_responses": len(valid_by_id),
        "invalid_responses": len(errors),
        "errors": errors,
        "write_allowed": not errors and len(valid_by_id) == len(pending),
    }
    if not report["write_allowed"]:
        return reviews, report

    merged: list[dict[str, Any]] = []
    changed_labels = 0
    for row in reviews:
        sample_id = str(row["sample_id"])
        response = valid_by_id.get(sample_id)
        if response is None:
            merged.append(dict(row))
            continue
        old_label = str(row.get("human_label", ""))
        new_label = str(response["second_label"]).strip()
        changed_labels += old_label != new_label
        updated = dict(row)
        updated.update(
            {
                "human_label": new_label,
                "human_confidence": str(response["second_confidence"]).strip(),
                "notes": str(response["second_rationale"]).strip(),
                "needs_review": False,
                "truth_status": "independent_second_pass_complete",
                "adjudication_source": "independent_second_pass_workbook",
                "first_pass_label": old_label,
            }
        )
        merged.append(updated)

    report["changed_labels"] = changed_labels
    report["remaining_needs_review"] = sum(
        bool(row.get("needs_review")) for row in merged
    )
    return merged, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reviews",
        type=Path,
        default=DEFAULT_MODEL_ROOT
        / "data"
        / "annotation_workbench"
        / "new_events_reviews.jsonl",
    )
    parser.add_argument(
        "--queue",
        type=Path,
        default=DEFAULT_MODEL_ROOT
        / "data"
        / "annotation_workbench"
        / "new_events_queue.jsonl",
        help="Only validation/test rows in this event-isolated queue are expected.",
    )
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "new_events_reviews_second_pass.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "second_pass_import_report.json",
    )
    args = parser.parse_args()

    reviews = read_jsonl(args.reviews)
    queue = read_jsonl(args.queue)
    expected_sample_ids = {
        str(row["sample_id"])
        for row in queue
        if str(row.get("split")) in {"validation", "test"}
    }
    responses = json.loads(args.responses.read_text(encoding="utf-8"))
    if not isinstance(responses, list):
        raise SystemExit("Responses must be a JSON array.")

    merged, report = validate_and_merge(
        reviews,
        responses,
        expected_sample_ids=expected_sample_ids,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["write_allowed"]:
        raise SystemExit(
            "Import blocked: correct every row listed in the report; no merged file was written."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in merged) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote validated second-pass reviews: {args.output}")


if __name__ == "__main__":
    main()
