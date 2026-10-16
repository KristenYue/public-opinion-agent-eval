"""Regenerate the paired Runtime gate report from committed records."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.runtime_gate import write_runtime_gate_report  # noqa: E402


def main() -> int:
    report = write_runtime_gate_report(
        PROJECT_ROOT,
        PROJECT_ROOT / "data/evaluation/runtime_eval_report_v1.json",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
