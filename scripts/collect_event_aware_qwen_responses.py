"""Collect blind Qwen predictions for event-isolated cascade evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import json
import os
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT.parent / "本科毕设_情感分析_恢复版"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.nodes import build_sentiment_classifier_node  # noqa: E402
from opinion_agent.agent.reviewer import OpenAICompatibleReviewer  # noqa: E402
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queue",
        type=Path,
        default=MODEL_ROOT / "data" / "annotation_workbench" / "new_events_queue.jsonl",
    )
    parser.add_argument("--split", choices=["validation", "test"], required=True)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "event_aware_qwen_responses_v2.jsonl",
    )
    args = parser.parse_args()
    missing_env = [
        name for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not os.getenv(name)
    ]
    if missing_env:
        raise SystemExit(f"BLOCKED: missing environment variables: {missing_env}")
    if args.batch_size < 1:
        raise ValueError("batch-size must be positive")

    queue = [row for row in read_jsonl(args.queue) if str(row["split"]) == args.split]
    existing_rows = read_jsonl(args.output)
    existing = {str(row["sample_id"]): row for row in existing_rows}
    pending = [row for row in queue if str(row["sample_id"]) not in existing]
    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    secondary = SnowNLPSentimentClassifier()
    classify = build_sentiment_classifier_node(classifier, secondary)
    reviewer = OpenAICompatibleReviewer(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "3")),
    )

    batches = []
    for event_id in sorted({str(row["event_id"]) for row in pending}):
        event_rows = [row for row in pending if str(row["event_id"]) == event_id]
        batches.extend(
            event_rows[start : start + args.batch_size]
            for start in range(0, len(event_rows), args.batch_size)
        )
    completed = 0
    for batch in batches:
        state = {
            "request_id": str(uuid.uuid4()),
            "event_id": str(batch[0]["event_id"]),
            "query": "结合事件目标与原帖背景，判断评论对事件目标的情感立场。",
            "comments": [
                {
                    "sample_id": str(row["sample_id"]),
                    "text": str(row["content"]),
                    "context": (
                        f"事件目标：{row.get('target', '')}\n"
                        f"原帖背景：{row.get('post_text', '')}"
                    ),
                }
                for row in batch
            ],
            "tool_traces": [],
            "errors": [],
        }
        classified = classify(state)  # type: ignore[arg-type]
        forced_results = [
            {**result, "force_qwen_evaluation": True}
            for result in classified["sentiment_results"]
        ]
        response = reviewer.review({**state, "sentiment_results": forced_results})  # type: ignore[arg-type]
        event_by_id = {str(row["sample_id"]): str(row["event_id"]) for row in batch}
        for item in response["items"]:
            sample_id = str(item["sample_id"])
            existing[sample_id] = {
                **item,
                "event_id": event_by_id[sample_id],
                "split": args.split,
                "reviewer": response["reviewer"],
                "prompt_version": response.get("prompt_version", "unknown"),
                "blind_to_human_label": True,
            }
        write_jsonl_atomic(args.output, list(existing.values()))
        completed += len(batch)
        print(f"saved {completed}/{len(pending)} pending rows")

    print(f"complete: {len(queue)} {args.split} rows; output={args.output}")


if __name__ == "__main__":
    main()
