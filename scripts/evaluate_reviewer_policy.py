"""Replay saved live reviewer responses under baseline and gated policies."""

from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.reviewer_policy import evaluate_override_policy  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--responses",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "llm_reviewer_responses.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "reviewer_policy_metrics.json",
    )
    parser.add_argument(
        "--independent-validation",
        action="store_true",
        help="Mark this replay as the pre-registered non-overlapping validation run.",
    )
    args = parser.parse_args()
    data = PROJECT_ROOT / "data" / "evaluation"
    cases = read_jsonl(data / "reviewer_eval_cases.jsonl")
    responses = read_jsonl(args.responses)
    report = {
        "evaluation_type": (
            "independent_non_overlapping_validation"
            if args.independent_validation
            else "exploratory_same_sample_replay"
        ),
        "warning": (
            "Frozen policy evaluated on non-overlapping cases; sample size remains small."
            if args.independent_validation
            else "Exploratory same-sample replay; not an independent validation result."
        ),
        "always_override": evaluate_override_policy(cases, responses),
        "high_confidence_disagreement_only": evaluate_override_policy(
            cases,
            responses,
            allowed_confidence=frozenset({"High"}),
            allowed_reasons=frozenset({"model_disagreement"}),
        ),
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
