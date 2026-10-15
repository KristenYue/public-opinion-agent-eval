"""Application service for idempotent asynchronous analysis jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opinion_agent.governance import SecurityPolicy, redact_sensitive

from .contracts import JobStatus, RunVersionSnapshot


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CommentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=5000)
    context: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=2000)


class JobSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    requested_by: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2000)
    comments: list[CommentSubmission] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_unique_sample_ids(self) -> "JobSubmission":
        sample_ids = [comment.sample_id for comment in self.comments]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("comment sample_id values must be unique within a job")
        return self

    def replay_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    project_id: UUID
    requested_by: str
    idempotency_key: str
    status: JobStatus
    event_id: str
    query: str
    request_payload: dict[str, Any]
    result_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    recovery_count: int = 0


@dataclass(frozen=True)
class CreateJobResult:
    job: JobRecord
    created: bool


class ClaimedRun(BaseModel):
    """A job and its durable run row claimed by exactly one worker attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job: JobRecord
    run_id: UUID
    trace_id: str
    lease_owner: str
    resume_state: dict[str, Any]


class JobRepository(Protocol):
    async def ping(self) -> bool: ...

    async def create_or_get(
        self,
        submission: JobSubmission,
        idempotency_key: str,
    ) -> CreateJobResult: ...

    async def get(self, job_id: UUID) -> JobRecord | None: ...

    async def fail_queued_job(
        self, job_id: UUID, error_code: str, message: str
    ) -> None: ...

    async def claim_for_execution(
        self,
        job_id: UUID,
        snapshot: RunVersionSnapshot,
        trace_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedRun | None: ...

    async def heartbeat(self, claim: ClaimedRun, lease_seconds: int) -> bool: ...

    async def recover_stale_jobs(self, max_attempts: int) -> dict[UUID, JobStatus]: ...

    async def finish_execution(
        self,
        claim: ClaimedRun,
        result: dict[str, Any],
        status: JobStatus,
    ) -> None: ...

    async def record_execution_failure(
        self,
        claim: ClaimedRun,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        max_attempts: int,
    ) -> JobStatus: ...


class JobDispatcher(Protocol):
    async def ping(self) -> bool: ...

    async def enqueue(self, job_id: UUID) -> None: ...


class IdempotencyConflictError(ValueError):
    """A key was reused with a different normalized request."""


class JobDispatchError(RuntimeError):
    """A durable job exists but could not be handed to the queue."""


class JobService:
    def __init__(
        self,
        repository: JobRepository,
        dispatcher: JobDispatcher,
        security_policy: SecurityPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.security_policy = security_policy or SecurityPolicy.from_env()

    async def submit(
        self,
        submission: JobSubmission,
        idempotency_key: str,
    ) -> CreateJobResult:
        raw_payload = submission.model_dump(mode="json")
        self.security_policy.validate_request_payload(raw_payload)
        sanitized_payload = redact_sensitive(raw_payload)
        # The principal is audit identity, not free-form analysis content. It
        # will be replaced by authenticated server identity in a later stage.
        sanitized_payload["requested_by"] = raw_payload["requested_by"]
        sanitized_submission = JobSubmission.model_validate(sanitized_payload)
        result = await self.repository.create_or_get(
            sanitized_submission,
            idempotency_key,
        )
        if not result.created:
            return result
        try:
            await self.dispatcher.enqueue(result.job.id)
        except Exception as exc:
            await self.repository.fail_queued_job(
                result.job.id,
                "queue_unavailable",
                f"{type(exc).__name__}: {str(exc)[:500]}",
            )
            raise JobDispatchError("analysis job could not be queued") from exc
        return result

    async def get(self, job_id: UUID) -> JobRecord | None:
        return await self.repository.get(job_id)

    async def readiness(self) -> dict[str, bool]:
        """Probe both durable dependencies without mutating application data."""

        database = await self.repository.ping()
        queue = await self.dispatcher.ping()
        return {"database": database, "queue": queue}
