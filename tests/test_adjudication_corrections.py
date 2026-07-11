from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from apply_adjudication_corrections import apply_corrections  # noqa: E402


def test_corrections_overlay_only_targeted_response() -> None:
    base = [
        {
            "sample_id": "a",
            "second_label": "Neutral",
            "second_confidence": "High",
            "changed_original_label": "No",
            "adjudication_note": "",
        },
        {"sample_id": "b", "second_label": "Positive"},
    ]
    corrections = [
        {
            "sample_id": "a",
            "second_label": "Negative",
            "second_confidence": "Medium",
            "changed_original_label": "Yes",
            "adjudication_note": "Explicit criticism.",
        }
    ]

    merged, report = apply_corrections(base, corrections)

    assert merged[0]["second_label"] == "Negative"
    assert merged[0]["adjudication_note"] == "Explicit criticism."
    assert merged[1] == base[1]
    assert report["applied_corrections"] == 1
    assert report["missing_correction_notes"] == 0


def test_blank_correction_flag_keeps_existing_mechanical_value() -> None:
    base = [
        {
            "sample_id": "a",
            "second_label": "Positive",
            "changed_original_label": "No",
            "adjudication_note": "",
        }
    ]
    corrections = [
        {
            "sample_id": "a",
            "second_label": "Positive",
            "second_confidence": "High",
            "changed_original_label": "",
            "adjudication_note": "Explicit praise.",
        }
    ]

    merged, _ = apply_corrections(base, corrections)

    assert merged[0]["changed_original_label"] == "No"
