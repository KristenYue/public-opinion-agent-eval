from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.data_pipeline import audit_comment_files  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="审计并脱敏去重原始评论")
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "data" / "raw_private" / "events")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "processed")
    args = parser.parse_args()

    data, audit = audit_comment_files(args.raw_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output_dir / "comments_deduplicated.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "data_audit.json").write_text(
        json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
