"""Build disjoint event-level batches for end-to-end agent evaluation."""

from collections import Counter, defaultdict
from pathlib import Path
from argparse import ArgumentParser
import json
import random


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "evaluation" / "evaluation_cases.jsonl"
OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "agent_eval_tasks.jsonl"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.source.read_text(encoding="utf-8").split("\n")
        if line
    ]
    by_event: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_event[str(row["event_id"])].append(row)

    rng = random.Random(20260621)
    tasks: list[dict[str, object]] = []
    for event_id, event_rows in sorted(by_event.items()):
        rng.shuffle(event_rows)
        batches = [event_rows[index::3] for index in range(3)]
        for batch_index, batch in enumerate(batches, start=1):
            if not batch:
                continue
            labels = [str(row["human_label"]) for row in batch]
            truth_statuses = sorted(
                {str(row.get("truth_status", "unknown")) for row in batch}
            )
            tasks.append(
                {
                    "task_id": f"{event_id}-batch-{batch_index}",
                    "event_id": event_id,
                    "split": batch[0]["split"],
                    "query": f"分析{event_id}事件的评论情绪，并检索可信的历史相似事件",
                    "comments": [
                        {"sample_id": row["sample_id"], "text": row["content"]}
                        for row in batch
                    ],
                    "expected_labels": {
                        str(row["sample_id"]): row["human_label"] for row in batch
                    },
                    "expected_distribution": dict(Counter(labels)),
                    "truth_status": (
                        truth_statuses[0]
                        if len(truth_statuses) == 1
                        else "mixed_partial_second_pass"
                    ),
                }
            )

    args.output.write_text(
        "\n".join(json.dumps(task, ensure_ascii=False) for task in tasks) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"tasks": len(tasks), "events": len(by_event), "output": str(args.output)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
