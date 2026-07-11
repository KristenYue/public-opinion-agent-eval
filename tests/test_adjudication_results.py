from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import (  # noqa: E402
    merge_adjudication_results,
    validate_adjudication_response,
)


def source_row() -> dict[str, object]:
    return {
        "sample_id": "sample-1",
        "human_label": "Neutral",
        "human_confidence": "High",
        "notes": "first pass",
        "truth_status": "provisional_single_annotator",
    }


def test_valid_changed_response_is_merged_with_provenance() -> None:
    response = {
        "sample_id": "sample-1",
        "second_label": "Negative",
        "second_confidence": "Medium",
        "changed_original_label": "Yes",
        "adjudication_note": "The wording is explicitly critical.",
    }

    merged, report = merge_adjudication_results([source_row()], [response])

    assert merged[0]["human_label"] == "Negative"
    assert merged[0]["human_label_previous"] == "Neutral"
    assert merged[0]["truth_status"] == "second_pass_adjudicated"
    assert report["valid_adjudications"] == 1
    assert report["label_changes"] == 1


def test_incomplete_response_does_not_replace_provisional_label() -> None:
    response = {
        "sample_id": "sample-1",
        "second_label": "Negative",
        "second_confidence": "Medium",
        "changed_original_label": "Yes",
        "adjudication_note": "",
    }

    merged, report = merge_adjudication_results([source_row()], [response])

    assert merged[0]["human_label"] == "Neutral"
    assert merged[0]["adjudication_status"] == "not_adjudicated"
    assert report["valid_adjudications"] == 0
    assert report["issue_counts"]["missing_adjudication_note"] == 1


def test_changed_flag_must_match_label_difference() -> None:
    response = {
        "sample_id": "sample-1",
        "second_label": "Negative",
        "second_confidence": "High",
        "changed_original_label": "No",
        "adjudication_note": "Critical wording.",
    }

    assert validate_adjudication_response(response, source_row()) == [
        "changed_flag_mismatch"
    ]
