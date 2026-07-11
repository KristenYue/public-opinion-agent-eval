from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.adjudication import (  # noqa: E402
    adjudication_reasons,
    build_adjudication_queue,
    summarize_adjudication_queue,
)


def test_models_agree_against_label_gets_high_priority_reason() -> None:
    row = {
        "sample_id": "a",
        "event_id": "event",
        "content": "能不能尊重一下人家",
        "human_label": "Negative",
        "human_confidence": "High",
        "notes": "",
        "xgb_suggestion": "Neutral",
        "snownlp_suggestion": "Neutral",
    }

    reasons = adjudication_reasons(row)
    queue = build_adjudication_queue([row])

    assert "models_agree_against_label" in reasons
    assert queue[0]["adjudication_priority"] == "High"


def test_short_high_confidence_without_note_is_reviewed() -> None:
    row = {
        "sample_id": "b",
        "event_id": "event",
        "content": "哎",
        "human_label": "Negative",
        "human_confidence": "High",
        "notes": "",
        "xgb_suggestion": "Neutral",
        "snownlp_suggestion": "Neutral",
    }

    reasons = adjudication_reasons(row)

    assert "short_text" in reasons
    assert "high_confidence_without_note" in reasons


def test_summary_counts_candidates_and_reasons() -> None:
    rows = [
        {
            "sample_id": "a",
            "event_id": "event",
            "content": "很好",
            "human_label": "Positive",
            "human_confidence": "High",
            "notes": "",
            "xgb_suggestion": "Positive",
            "snownlp_suggestion": "Positive",
        },
        {
            "sample_id": "b",
            "event_id": "event",
            "content": "哎",
            "human_label": "Negative",
            "human_confidence": "High",
            "notes": "",
            "xgb_suggestion": "Neutral",
            "snownlp_suggestion": "Neutral",
        },
    ]
    queue = build_adjudication_queue(rows)
    summary = summarize_adjudication_queue(rows, queue)

    assert summary["source_samples"] == 2
    assert summary["adjudication_candidates"] == 2
    assert summary["reason_counts"]["short_text"] == 2
