"""Generate the portfolio repository release-readiness report."""

from pathlib import Path
import argparse
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.release_readiness import (  # noqa: E402
    evaluate_release_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "release_readiness.json",
    )
    args = parser.parse_args()
    report = evaluate_release_readiness(PROJECT_ROOT)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
