"""Versioned public task bundle for paired Runtime evaluation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


TaskCategory = Literal[
    "standard",
    "ambiguous",
    "sensitive_input",
    "candidate_failure",
    "timeout",
    "contract_violation",
]
FaultMode = Literal["none", "candidate_failure", "timeout", "contract_violation"]


class RuntimeEvaluationTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runtime-opinion-task/v1"]
    case_id: str = Field(pattern=r"^runtime-v1-\d{3}$")
    category: TaskCategory
    event_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2000)
    comment_text: str = Field(min_length=1, max_length=5000)
    fault_mode: FaultMode = "none"
    expected_official_status: Literal["completed"] = "completed"
    expected_shadow_status: Literal["succeeded", "failed", "timed_out"]
    must_redact: bool = False


class RuntimeTaskManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["runtime-opinion-manifest/v1"]
    dataset_version: Literal["runtime-opinion-v1"]
    dataset_path: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_count: int = Field(ge=50, le=100)
    category_counts: dict[str, int]
    thresholds: dict[str, float]


def load_runtime_task_bundle(
    dataset_path: str | Path, manifest_path: str | Path
) -> tuple[list[RuntimeEvaluationTask], RuntimeTaskManifest]:
    dataset = Path(dataset_path)
    manifest = RuntimeTaskManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8")
    )
    raw = dataset.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest.dataset_sha256:
        raise ValueError("runtime task dataset SHA-256 mismatch")

    tasks = [
        RuntimeEvaluationTask.model_validate_json(line)
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    if len(tasks) != manifest.task_count:
        raise ValueError("runtime task count does not match manifest")
    case_ids = [task.case_id for task in tasks]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("runtime task case_id values must be unique")
    counts = dict(sorted(Counter(task.category for task in tasks).items()))
    if counts != manifest.category_counts:
        raise ValueError("runtime task category counts do not match manifest")
    if not 50 <= len(tasks) <= 100:
        raise ValueError("runtime task bundle must contain 50 to 100 tasks")
    return tasks, manifest
