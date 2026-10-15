from pathlib import Path

import pytest

from opinion_agent.evaluation.runtime_tasks import load_runtime_task_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "examples/runtime_eval_tasks_v1.jsonl"
MANIFEST = PROJECT_ROOT / "data/evaluation/runtime_eval_tasks_v1_manifest.json"


def test_runtime_task_bundle_is_frozen_balanced_and_public() -> None:
    tasks, manifest = load_runtime_task_bundle(DATASET, MANIFEST)

    assert len(tasks) == 60
    assert set(manifest.category_counts.values()) == {10}
    assert all(task.event_id.startswith("示例-") for task in tasks)
    assert all("example.com" not in task.comment_text for task in tasks)
    assert manifest.thresholds == {
        "max_success_rate_drop": 0.0,
        "max_quality_drop": 0.02,
        "max_error_increase": 0.0,
        "max_latency_increase_ms": 100.0,
        "max_cost_increase_usd": 0.01,
    }


def test_runtime_task_bundle_rejects_tampering(tmp_path: Path) -> None:
    tampered = tmp_path / "tasks.jsonl"
    tampered.write_bytes(DATASET.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_runtime_task_bundle(tampered, MANIFEST)
