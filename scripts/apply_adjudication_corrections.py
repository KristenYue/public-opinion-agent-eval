"""Overlay focused correction responses onto the full adjudication response set."""

from pathlib import Path
import argparse
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def apply_corrections(
    base_rows: list[dict[str, object]],
    corrections: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    base_by_id = {str(row.get("sample_id", "")): row for row in base_rows}
    unknown_ids: list[str] = []
    applied = 0
    for correction in corrections:
        sample_id = str(correction.get("sample_id", "")).strip()
        if sample_id not in base_by_id:
            unknown_ids.append(sample_id)
            continue
        overlay = {
            "second_label": correction.get("second_label", ""),
            "second_confidence": correction.get("second_confidence", ""),
            "adjudication_note": correction.get("adjudication_note", ""),
        }
        changed_flag = str(correction.get("changed_original_label", "")).strip()
        if changed_flag:
            overlay["changed_original_label"] = changed_flag
        base_by_id[sample_id].update(overlay)
        applied += 1

    missing_notes = sum(
        not str(row.get("adjudication_note", "")).strip() for row in corrections
    )
    return list(base_by_id.values()), {
        "base_rows": len(base_rows),
        "correction_rows": len(corrections),
        "applied_corrections": applied,
        "missing_correction_notes": missing_notes,
        "unknown_sample_ids": unknown_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "adjudication_responses.jsonl",
    )
    parser.add_argument(
        "--corrections",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "adjudication_correction_responses.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "adjudication_responses_corrected.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "evaluation"
        / "adjudication_correction_report.json",
    )
    args = parser.parse_args()

    merged, report = apply_corrections(
        read_jsonl(args.base),
        read_jsonl(args.corrections),
    )
    write_jsonl(args.output, merged)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
