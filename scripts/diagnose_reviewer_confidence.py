"""Diagnose frozen blind Qwen responses without making new API calls."""

from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.reviewer_diagnostics import diagnose_reviewer  # noqa: E402
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


EVALUATION_ROOT = PROJECT_ROOT / "data" / "evaluation"


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=EVALUATION_ROOT / "benchmark_v1_5_queue.jsonl")
    parser.add_argument("--reviews", type=Path, default=EVALUATION_ROOT / "benchmark_v1_5_reviews.jsonl")
    parser.add_argument(
        "--responses", type=Path, default=EVALUATION_ROOT / "benchmark_v1_5_qwen_responses.jsonl"
    )
    parser.add_argument("--split", choices=["validation", "test"], default="test")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--short-text-max-chars", type=int, default=4)
    parser.add_argument(
        "--output", type=Path, default=EVALUATION_ROOT / "reviewer_confidence_diagnostics.json"
    )
    args = parser.parse_args()

    queue = [row for row in read_jsonl(args.queue) if str(row.get("split")) == args.split]
    reviews = {str(row["sample_id"]): row for row in read_jsonl(args.reviews)}
    responses = {str(row["sample_id"]): row for row in read_jsonl(args.responses)}
    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    secondary = SnowNLPSentimentClassifier()

    rows = []
    for row in queue:
        sample_id = str(row["sample_id"])
        if sample_id not in reviews:
            raise SystemExit(f"missing human review for {sample_id}")
        text = str(row["content"])
        try:
            primary = classifier.predict(text)
            xgb_label, xgb_confidence = primary.label, primary.confidence
        except ValueError as exc:
            if str(exc) != "Text is empty after preprocessing":
                raise
            xgb_label, xgb_confidence = "Unscorable", 0.0
        rows.append(
            {
                **row,
                "gold": normalize_label(reviews[sample_id]["human_label"]),
                "xgb_label": xgb_label,
                "xgb_confidence": xgb_confidence,
                "secondary_label": secondary.predict(text).label,
            }
        )

    normalized_responses = {
        sample_id: {**response, "label": normalize_label(response["label"])}
        for sample_id, response in responses.items()
    }
    result = {
        "protocol": "frozen_blind_reviewer_confidence_v1",
        "split": args.split,
        "new_api_calls": 0,
        "blind_to_human_label": all(
            bool(response.get("blind_to_human_label"))
            for response in normalized_responses.values()
            if str(response.get("split")) == args.split
        ),
        "diagnostics": diagnose_reviewer(
            rows,
            normalized_responses,
            threshold=args.threshold,
            short_text_max_chars=args.short_text_max_chars,
        ),
        "limitations": [
            "Confidence labels are reviewer self-reports, not calibrated probabilities.",
            "This reuses one frozen response per sample and does not measure repeated-call consistency.",
            "Anchoring and order sensitivity require separately randomized new API calls.",
        ],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def normalize_label(value: object) -> str:
    label = str(value)
    return "Unscorable" if label == "Exclude" else label


if __name__ == "__main__":
    main()
