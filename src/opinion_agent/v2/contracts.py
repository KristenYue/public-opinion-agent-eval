"""Stable V2 persistence contracts independent of a database driver.

Week 1 deliberately freezes these contracts before the asynchronous worker and
PostgreSQL repository are wired in.  Keeping state transitions here prevents
the API, worker and review UI from inventing conflicting lifecycle rules.
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobStatus(StrEnum):
    """Externally visible lifecycle of one analysis job."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DEGRADED = "degraded"
    MANUAL_REQUIRED = "manual_required"
    FAILED_CLOSED = "failed_closed"
    COMPLETED = "completed"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.FAILED_CLOSED, JobStatus.COMPLETED})

ALLOWED_JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED_CLOSED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.RETRYING,
            JobStatus.DEGRADED,
            JobStatus.MANUAL_REQUIRED,
            JobStatus.FAILED_CLOSED,
            JobStatus.COMPLETED,
        }
    ),
    JobStatus.RETRYING: frozenset(
        {
            JobStatus.RUNNING,
            JobStatus.DEGRADED,
            JobStatus.MANUAL_REQUIRED,
            JobStatus.FAILED_CLOSED,
        }
    ),
    JobStatus.DEGRADED: frozenset(
        {
            JobStatus.RETRYING,
            JobStatus.MANUAL_REQUIRED,
            JobStatus.FAILED_CLOSED,
            JobStatus.COMPLETED,
        }
    ),
    JobStatus.MANUAL_REQUIRED: frozenset(
        {JobStatus.RUNNING, JobStatus.FAILED_CLOSED, JobStatus.COMPLETED}
    ),
    JobStatus.FAILED_CLOSED: frozenset(),
    JobStatus.COMPLETED: frozenset(),
}


def can_transition_job(current: JobStatus | str, target: JobStatus | str) -> bool:
    """Return whether a persisted job may move to ``target``."""

    current_status = JobStatus(current)
    target_status = JobStatus(target)
    return target_status in ALLOWED_JOB_TRANSITIONS[current_status]


def assert_job_transition(current: JobStatus | str, target: JobStatus | str) -> None:
    """Raise a useful error before an invalid lifecycle update reaches storage."""

    current_status = JobStatus(current)
    target_status = JobStatus(target)
    if not can_transition_job(current_status, target_status):
        raise ValueError(
            f"invalid analysis job transition: {current_status.value} -> {target_status.value}"
        )


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class VersionedComponent(BaseModel):
    """Immutable identity of a model, prompt, tool set, or policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("name", "version")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("component identity must not contain surrounding whitespace")
        return value

    def resolved_hash(self) -> str:
        """Use a supplied artifact hash, or deterministically hash public config."""

        return self.config_sha256 or _canonical_hash(self.config)


class RunVersionSnapshot(BaseModel):
    """Everything needed to explain which executable contract produced a run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: VersionedComponent
    prompt: VersionedComponent
    toolset: VersionedComponent
    policy: VersionedComponent

    def fingerprint(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))
