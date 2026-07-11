"""Prepare or execute the structured LLM reviewer benchmark."""

from pathlib import Path
import argparse
import json
import os
import sys
from collections import defaultdict, deque


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.reviewer import OpenAICompatibleReviewer  # noqa: E402
from opinion_agent.evaluation import run_reviewer_benchmark  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def select_small_scale_cases(
    cases: list[dict[str, object]],
    max_cases: int | None,
    excluded_sample_ids: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    """Select a deterministic, reason-balanced subset of reviewable cases."""
    selected = [
        case
        for case in cases
        if case.get("selected_for_review")
        and str(case.get("sample_id", "")) not in excluded_sample_ids
    ]
    if max_cases is None or max_cases >= len(selected):
        return selected
    if max_cases < 1:
        raise ValueError("max_cases must be positive")

    groups: dict[str, deque[dict[str, object]]] = defaultdict(deque)
    for case in selected:
        groups[str(case.get("selection_reason", "unknown"))].append(case)

    subset: list[dict[str, object]] = []
    reasons = sorted(groups)
    while len(subset) < max_cases:
        made_progress = False
        for reason in reasons:
            if groups[reason] and len(subset) < max_cases:
                subset.append(groups[reason].popleft())
                made_progress = True
        if not made_progress:
            break
    return subset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "reviewer_eval_cases.jsonl",
    )
    parser.add_argument(
        "--selection-summary",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "reviewer_eval_summary.json",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "llm_reviewer_metrics.json",
    )
    parser.add_argument(
        "--responses-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "llm_reviewer_responses.jsonl",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Limit execution to a deterministic, reason-balanced selected subset.",
    )
    parser.add_argument(
        "--exclude-responses",
        type=Path,
        help="JSONL responses whose sample IDs must be excluded from this run.",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    all_cases = read_jsonl(args.cases)
    excluded_ids = frozenset(
        str(row["sample_id"])
        for row in read_jsonl(args.exclude_responses)
    ) if args.exclude_responses else frozenset()
    cases = select_small_scale_cases(all_cases, args.max_cases, excluded_ids)
    selection = json.loads(args.selection_summary.read_text(encoding="utf-8"))
    configured = all(os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"))
    if not args.execute:
        selected = len(cases)
        readiness = {
            "status": "ready_to_execute" if configured else "missing_llm_configuration",
            "executed": False,
            "provider_configured": configured,
            "focused_candidates": len(all_cases),
            "selected_cases": selected,
            "max_cases": args.max_cases,
            "excluded_cases": len(excluded_ids),
            "selection_metrics": selection,
            "next_command": "python scripts/evaluate_llm_reviewer.py --execute --max-cases 12",
        }
        args.metrics_output.write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return
    if not configured:
        raise SystemExit(
            "LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are required with --execute"
        )

    reviewer = OpenAICompatibleReviewer(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
    )
    metrics, responses = run_reviewer_benchmark(
        cases, reviewer, batch_size=args.batch_size
    )
    metrics["selection_metrics"] = selection
    metrics["model"] = os.environ["LLM_MODEL"]
    args.metrics_output.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.responses_output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in responses) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
