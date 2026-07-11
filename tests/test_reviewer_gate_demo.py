from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def test_demo_contains_one_safe_apply_and_one_safe_reject() -> None:
    demo = json.loads(
        (ROOT / "examples" / "reviewer_gate_demo.json").read_text(encoding="utf-8")
    )
    applied = [case for case in demo["cases"] if case["applied"]]
    rejected = [case for case in demo["cases"] if not case["applied"]]

    assert len(applied) == 1
    assert applied[0]["final_label"] == applied[0]["expected_label"]
    assert len(rejected) == 1
    assert rejected[0]["final_label"] == rejected[0]["expected_label"]
