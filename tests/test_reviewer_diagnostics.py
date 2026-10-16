from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.reviewer_diagnostics import diagnose_reviewer  # noqa: E402


def test_diagnostics_separate_confidence_and_governed_overrides() -> None:
    rows = [
        {
            "sample_id": "a",
            "gold": "Negative",
            "xgb_label": "Neutral",
            "xgb_confidence": 0.5,
            "secondary_label": "Negative",
            "content": "bad service",
        },
        {
            "sample_id": "b",
            "gold": "Positive",
            "xgb_label": "Positive",
            "xgb_confidence": 0.9,
            "secondary_label": "Positive",
            "content": "good service",
        },
        {
            "sample_id": "c",
            "gold": "Negative",
            "xgb_label": "Negative",
            "xgb_confidence": 0.4,
            "secondary_label": "Neutral",
            "content": "unclear",
        },
    ]
    responses = {
        "a": {"label": "Negative", "confidence": "High"},
        "b": {"label": "Negative", "confidence": "High"},
        "c": {"label": "Neutral", "confidence": "Medium"},
    }

    result = diagnose_reviewer(rows, responses, threshold=0.8, short_text_max_chars=4)

    assert result["confidence_strata"]["High"] == {"count": 2, "accuracy": 0.5}
    assert result["unconditional_override"] == {
        "overrides": 3,
        "corrected": 1,
        "harmful": 2,
        "wrong_to_wrong": 0,
        "net_corrections": -1,
    }
    assert result["governed_policy"]["path_counts"] == {
        "fast_path": 1,
        "qwen_reviewed": 1,
        "manual_required": 1,
    }
    assert result["governed_policy"]["corrected"] == 1
    assert result["governed_policy"]["harmful"] == 0


def test_diagnostics_reject_missing_response() -> None:
    try:
        diagnose_reviewer(
            [{"sample_id": "missing"}],
            {},
            threshold=0.8,
            short_text_max_chars=4,
        )
    except ValueError as exc:
        assert "missing reviewer responses" in str(exc)
    else:
        raise AssertionError("expected missing response validation")
