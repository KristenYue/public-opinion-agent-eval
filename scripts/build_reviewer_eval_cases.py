"""Build a focused benchmark for reviewer selection and LLM adjudication."""

from pathlib import Path
from collections import Counter
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.reviewer import review_selection_reason  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def reviewer_label(value: object) -> str:
    label = str(value or "").strip()
    return "Unscorable" if label in {"", "Exclude", "Unscorable"} else label


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "evaluation_cases_partial_adjudication.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "reviewer_eval_cases.jsonl",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "reviewer_eval_summary.json",
    )
    args = parser.parse_args()

    source = read_jsonl(args.source)
    candidates = [
        row
        for row in source
        if row.get("adjudication_status") == "adjudicated"
    ]
    cases: list[dict[str, object]] = []
    for row in candidates:
        xgb = reviewer_label(row.get("xgb_suggestion"))
        snow = reviewer_label(row.get("snownlp_suggestion"))
        expected = reviewer_label(row.get("human_label"))
        selection_reason = review_selection_reason(
            {
                "label": xgb,
                "models_agree": xgb == snow,
                "text": row.get("content", ""),
            }
        )
        selected = selection_reason is not None
        cases.append(
            {
                "sample_id": row["sample_id"],
                "event_id": row["event_id"],
                "split": row["split"],
                "text": row["content"],
                "context": row.get("post_text", ""),
                "source_url": row.get("post_url", ""),
                "xgb_label": xgb,
                "xgb_confidence": row.get("xgb_confidence"),
                "secondary_label": snow,
                "secondary_score": row.get("snownlp_score"),
                "expected_label": expected,
                "selected_for_review": selected,
                "selection_reason": selection_reason or "model_agreement",
                "baseline_error": xgb != expected,
            }
        )

    selected_cases = [row for row in cases if row["selected_for_review"]]
    missed_errors = [
        row for row in cases if row["baseline_error"] and not row["selected_for_review"]
    ]
    summary = {
        "policy_version": "multi_signal_v2",
        "selection_signals": ["unscorable", "model_disagreement", "short_text_context_risk"],
        "focused_candidates": len(cases),
        "selected_for_review": len(selected_cases),
        "selection_rate": len(selected_cases) / len(cases) if cases else 0.0,
        "baseline_errors": sum(bool(row["baseline_error"]) for row in cases),
        "selected_baseline_errors": sum(
            bool(row["baseline_error"]) for row in selected_cases
        ),
        "missed_baseline_errors": len(missed_errors),
        "error_selection_recall": (
            sum(bool(row["baseline_error"]) for row in selected_cases)
            / sum(bool(row["baseline_error"]) for row in cases)
            if any(row["baseline_error"] for row in cases)
            else 0.0
        ),
        "selection_reason_counts": dict(
            sorted(Counter(str(row["selection_reason"]) for row in selected_cases).items())
        ),
        "missed_error_sample_ids": [row["sample_id"] for row in missed_errors],
    }
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in cases) + "\n",
        encoding="utf-8",
    )
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
