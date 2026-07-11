"""Merge valid second-pass responses without overwriting provisional source data."""

from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import merge_adjudication_results  # noqa: E402


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
        "--source",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "annotations_provisional.jsonl",
    )
    parser.add_argument(
        "--responses",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "adjudication_responses.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "annotations_partially_adjudicated.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "adjudication_import_report.json",
    )
    args = parser.parse_args()

    merged, report = merge_adjudication_results(
        read_jsonl(args.source),
        read_jsonl(args.responses),
    )
    write_jsonl(args.output, merged)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
