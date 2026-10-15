"""Cross-repository paired Runtime evaluation for the frozen public task bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from .runtime_tasks import load_runtime_task_bundle


TASK_PATH = Path("examples/runtime_eval_tasks_v1.jsonl")
MANIFEST_PATH = Path("data/evaluation/runtime_eval_tasks_v1_manifest.json")
BASELINE_PATH = Path("examples/runtime_eval_baseline_v1.jsonl")
CANDIDATE_PATH = Path("examples/runtime_eval_candidate_v1.jsonl")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_runtime_gate(project_root: str | Path) -> dict[str, Any]:
    """Evaluate frozen scenario-level records with the pinned Runtime gate."""
    try:
        from agent_runtime_platform.evaluation import (
            GateThresholds,
            RunRecord,
            paired_regression_gate,
        )
    except ImportError as exc:  # pragma: no cover - exercised by deployment setup
        raise RuntimeError(
            "Runtime gate requires the pinned project shadow dependency"
        ) from exc

    root = Path(project_root)
    tasks, manifest = load_runtime_task_bundle(
        root / TASK_PATH,
        root / MANIFEST_PATH,
    )
    baseline = _load_records(root / BASELINE_PATH, RunRecord)
    candidate = _load_records(root / CANDIDATE_PATH, RunRecord)
    expected_ids = {task.case_id for task in tasks}
    _validate_record_ids("baseline", baseline, expected_ids)
    _validate_record_ids("candidate", candidate, expected_ids)

    thresholds = GateThresholds.model_validate(manifest.thresholds)
    gate = paired_regression_gate(baseline, candidate, thresholds=thresholds)
    return {
        "schema_version": "runtime-opinion-gate-report/v1",
        "evaluation_mode": "synthetic_contract_fixture",
        "status": "passed" if gate.passed else "blocked",
        "inputs": {
            "dataset_version": manifest.dataset_version,
            "task_sha256": file_sha256(root / TASK_PATH),
            "baseline_sha256": file_sha256(root / BASELINE_PATH),
            "candidate_sha256": file_sha256(root / CANDIDATE_PATH),
        },
        "thresholds": thresholds.model_dump(mode="json"),
        "gate": _round_floats(gate.model_dump(mode="json")),
        "limitations": [
            "Records are deterministic synthetic contract fixtures, not production traffic.",
            "A succeeded fault scenario means the expected containment outcome was observed.",
            "Latency and cost are calibration values and are not production SLA evidence.",
        ],
    }


def _load_records(path: Path, record_type: Any) -> list[Any]:
    return [
        record_type.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_record_ids(label: str, records: list[Any], expected: set[str]) -> None:
    actual = [record.case_id for record in records]
    if len(actual) != len(set(actual)):
        raise ValueError(f"duplicate {label} case_id")
    if set(actual) != expected:
        missing = sorted(expected - set(actual))
        extra = sorted(set(actual) - expected)
        raise ValueError(f"{label} case mismatch; missing={missing}, extra={extra}")


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    return value


def write_runtime_gate_report(project_root: str | Path, output: str | Path) -> dict[str, Any]:
    report = evaluate_runtime_gate(project_root)
    Path(output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
