"""Generate deterministic, public paired records for Runtime gate calibration."""

from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.runtime_gate import (  # noqa: E402
    BASELINE_PATH,
    CANDIDATE_PATH,
    MANIFEST_PATH,
    TASK_PATH,
    write_runtime_gate_report,
)
from opinion_agent.evaluation.runtime_tasks import load_runtime_task_bundle  # noqa: E402


def _record(task, index: int, *, candidate: bool) -> dict:
    safety_case = task.fault_mode != "none"
    baseline_quality = 0.96 if safety_case else 0.88 + (index % 3) * 0.01
    return {
        "case_id": task.case_id,
        "category": task.category,
        # Scenario-level success: expected completion or expected containment occurred.
        "succeeded": True,
        "quality_score": min(1.0, baseline_quality + (0.01 if candidate else 0.0)),
        "error_count": 0,
        "tool_call_count": 1 if safety_case else 2,
        "latency_ms": 125 + (index % 10) * 3 + (35 if candidate else 0),
        "estimated_cost_usd": round(
            0.002 + (index % 5) * 0.0001 + (0.0004 if candidate else 0), 6
        ),
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    payload = "".join(
        json.dumps(record, ensure_ascii=False) + "\n" for record in records
    )
    path.write_bytes(payload.encode("utf-8"))


def main() -> int:
    tasks, _ = load_runtime_task_bundle(
        PROJECT_ROOT / TASK_PATH,
        PROJECT_ROOT / MANIFEST_PATH,
    )
    _write_jsonl(
        PROJECT_ROOT / BASELINE_PATH,
        [_record(task, index, candidate=False) for index, task in enumerate(tasks)],
    )
    _write_jsonl(
        PROJECT_ROOT / CANDIDATE_PATH,
        [_record(task, index, candidate=True) for index, task in enumerate(tasks)],
    )
    report = write_runtime_gate_report(
        PROJECT_ROOT,
        PROJECT_ROOT / "data/evaluation/runtime_eval_report_v1.json",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
