"""Build a reproducible adjudication queue from provisional labels."""

from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import (  # noqa: E402
    build_adjudication_queue,
    summarize_adjudication_queue,
)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "annotations_provisional.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "adjudication_queue.jsonl",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "adjudication_summary.json",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.input)
    queue = build_adjudication_queue(rows)
    summary = summarize_adjudication_queue(rows, queue)

    write_jsonl(args.output, queue)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
