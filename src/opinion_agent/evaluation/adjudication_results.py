"""Validate second-pass decisions and merge only auditable adjudications."""

from collections import Counter
from collections.abc import Sequence


VALID_LABELS = {"Positive", "Negative", "Neutral", "Exclude"}
VALID_CONFIDENCE = {"High", "Medium", "Low"}
VALID_CHANGED_FLAGS = {"Yes", "No"}


def _text(value: object) -> str:
    return str(value or "").strip()


def validate_adjudication_response(
    response: dict[str, object],
    source_row: dict[str, object],
) -> list[str]:
    """Return machine-readable issues for one second-pass response."""
    label = _text(response.get("second_label"))
    confidence = _text(response.get("second_confidence"))
    changed = _text(response.get("changed_original_label"))
    note = _text(response.get("adjudication_note"))
    original = _text(source_row.get("human_label"))
    issues: list[str] = []

    if not label:
        issues.append("missing_second_label")
    elif label not in VALID_LABELS:
        issues.append("invalid_second_label")
    if not confidence:
        issues.append("missing_second_confidence")
    elif confidence not in VALID_CONFIDENCE:
        issues.append("invalid_second_confidence")
    if not changed:
        issues.append("missing_changed_flag")
    elif changed not in VALID_CHANGED_FLAGS:
        issues.append("invalid_changed_flag")
    if not note:
        issues.append("missing_adjudication_note")
    if label and changed in VALID_CHANGED_FLAGS:
        if (label != original) != (changed == "Yes"):
            issues.append("changed_flag_mismatch")
    return issues


def merge_adjudication_results(
    source_rows: Sequence[dict[str, object]],
    responses: Sequence[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Merge valid responses while preserving provisional rows and provenance."""
    source_by_id = {_text(row.get("sample_id")): row for row in source_rows}
    response_counts = Counter(_text(row.get("sample_id")) for row in responses)
    response_by_id = {
        sample_id: row
        for row in responses
        if (sample_id := _text(row.get("sample_id")))
    }
    issues: list[dict[str, object]] = []
    valid_by_id: dict[str, dict[str, object]] = {}

    for sample_id, response in response_by_id.items():
        if sample_id not in source_by_id:
            issues.append({"sample_id": sample_id, "issues": ["unknown_sample_id"]})
            continue
        row_issues = validate_adjudication_response(response, source_by_id[sample_id])
        if response_counts[sample_id] > 1:
            row_issues.append("duplicate_sample_id")
        if row_issues:
            issues.append({"sample_id": sample_id, "issues": row_issues})
        else:
            valid_by_id[sample_id] = response

    merged: list[dict[str, object]] = []
    label_changes = 0
    for source in source_rows:
        sample_id = _text(source.get("sample_id"))
        response = valid_by_id.get(sample_id)
        if response is None:
            merged.append({**source, "adjudication_status": "not_adjudicated"})
            continue

        second_label = _text(response["second_label"])
        changed = second_label != _text(source.get("human_label"))
        label_changes += int(changed)
        merged.append(
            {
                **source,
                "human_label_previous": source.get("human_label"),
                "human_confidence_previous": source.get("human_confidence"),
                "notes_previous": source.get("notes"),
                "human_label": second_label,
                "human_confidence": _text(response["second_confidence"]),
                "notes": _text(response["adjudication_note"]),
                "truth_status": "second_pass_adjudicated",
                "adjudication_status": "adjudicated",
                "adjudication_changed_label": changed,
                "adjudication_source": "second_pass_workbook",
            }
        )

    issue_counts = Counter(issue for row in issues for issue in row["issues"])
    valid_count = len(valid_by_id)
    report: dict[str, object] = {
        "source_samples": len(source_rows),
        "response_rows": len(responses),
        "valid_adjudications": valid_count,
        "adjudication_coverage": valid_count / len(source_rows) if source_rows else 0.0,
        "label_changes": label_changes,
        "retained_labels": valid_count - label_changes,
        "skipped_invalid_responses": len(issues),
        "issue_counts": dict(sorted(issue_counts.items())),
        "issues": issues,
        "truth_status": "mixed_partial_second_pass",
    }
    return merged, report
