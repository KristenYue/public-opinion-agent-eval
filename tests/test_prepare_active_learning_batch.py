from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_active_learning_batch.py"
SPEC = importlib.util.spec_from_file_location("prepare_active_learning_batch", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_priority_score_prefers_disagreement_and_negative_candidates() -> None:
    ordinary = {
        "content": "普通评论内容",
        "xgb_suggestion": "Neutral",
        "snownlp_suggestion": "Neutral",
        "xgb_confidence": 0.8,
        "xgb_negative_probability": 0.1,
        "snownlp_score": 0.5,
    }
    difficult = {
        **ordinary,
        "content": "不行",
        "xgb_suggestion": "Positive",
        "snownlp_suggestion": "Negative",
        "xgb_confidence": 0.55,
        "xgb_negative_probability": 0.7,
        "snownlp_score": 0.1,
    }

    ordinary_score, _ = MODULE.priority_score(ordinary)
    difficult_score, reasons = MODULE.priority_score(difficult)

    assert difficult_score > ordinary_score
    assert "model_disagreement" in reasons
    assert "negative_candidate" in reasons
    assert "short_text_context_risk" in reasons


def test_event_balanced_selection_does_not_let_one_event_dominate() -> None:
    rows = [
        *(
            {"sample_id": f"a-{index}", "event_id": "a", "selection_score": 100 - index}
            for index in range(10)
        ),
        *(
            {"sample_id": f"b-{index}", "event_id": "b", "selection_score": 10 - index}
            for index in range(3)
        ),
    ]

    selected = MODULE.select_event_balanced(rows, target_size=6)

    assert sum(row["event_id"] == "b" for row in selected) == 3
    assert len(selected) == 6
