"""Print an operator-facing explanation of the frozen Reviewer gate."""

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    demo = json.loads(
        (ROOT / "examples" / "reviewer_gate_demo.json").read_text(encoding="utf-8")
    )
    print(f"policy={demo['policy']}")
    for case in demo["cases"]:
        action = "APPLY" if case["applied"] else "REJECT"
        print(
            f"[{action}] {case['sample_id']} text={case['text']!r} "
            f"baseline={case['baseline_label']} suggestion={case['reviewer_suggestion']} "
            f"final={case['final_label']} reason={case['decision_reason']}"
        )


if __name__ == "__main__":
    main()
