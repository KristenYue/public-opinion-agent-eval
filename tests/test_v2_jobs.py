from datetime import datetime, timezone
from pathlib import Path
import sys
import tomllib
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.api import build_v2_job_service, create_app  # noqa: E402
from opinion_agent import __version__  # noqa: E402
from opinion_agent.governance import RequestBudgetExceeded, SecurityPolicy  # noqa: E402
from opinion_agent.v2.jobs import (  # noqa: E402
    CreateJobResult,
    IdempotencyConflictError,
    JobDispatchError,
    JobRecord,
    JobService,
    JobSubmission,
    JobTrace,
    canonical_payload_hash,
)


PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def _run_immediate(coroutine):
    """Drive fake-I/O coroutines without a Windows event loop in sandboxed tests."""

    try:
        yielded = coroutine.send(None)
    except StopIteration as stop:
        return stop.value
    coroutine.close()
    raise AssertionError(f"fake coroutine unexpectedly suspended with {yielded!r}")


def _submission(query: str = "分析事件") -> JobSubmission:
    return JobSubmission.model_validate(
        {
            "project_id": str(PROJECT_ID),
            "requested_by": "tester@example.com",
            "event_id": "事件A",
            "query": query,
            "comments": [{"sample_id": "c-1", "text": "这是一条评论"}],
        }
    )


class MemoryRepository:
    def __init__(self) -> None:
        self.by_key: dict[tuple[UUID, str], JobRecord] = {}
        self.by_id: dict[UUID, JobRecord] = {}
        self.failed: list[tuple[UUID, str, str]] = []

    async def ping(self) -> bool:
        return True

    async def create_or_get(
        self, submission: JobSubmission, idempotency_key: str
    ) -> CreateJobResult:
        key = (submission.project_id, idempotency_key)
        existing = self.by_key.get(key)
        payload = submission.replay_payload()
        if existing:
            if canonical_payload_hash(existing.request_payload) != canonical_payload_hash(payload):
                raise IdempotencyConflictError("different request")
            return CreateJobResult(existing, created=False)

        now = datetime.now(timezone.utc)
        job = JobRecord(
            id=uuid4(),
            project_id=submission.project_id,
            requested_by=submission.requested_by,
            idempotency_key=idempotency_key,
            status="queued",
            event_id=submission.event_id,
            query=submission.query,
            request_payload=payload,
            created_at=now,
            updated_at=now,
        )
        self.by_key[key] = job
        self.by_id[job.id] = job
        return CreateJobResult(job, created=True)

    async def get(self, job_id: UUID) -> JobRecord | None:
        return self.by_id.get(job_id)

    async def get_trace(self, job_id: UUID) -> JobTrace | None:
        job = self.by_id.get(job_id)
        return JobTrace(job=job) if job is not None else None

    async def fail_queued_job(
        self, job_id: UUID, error_code: str, message: str
    ) -> None:
        self.failed.append((job_id, error_code, message))


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.job_ids: list[UUID] = []

    async def ping(self) -> bool:
        return self.error is None

    async def enqueue(self, job_id: UUID) -> None:
        if self.error:
            raise self.error
        self.job_ids.append(job_id)


def test_submit_is_idempotent_and_only_enqueues_once() -> None:
    repository = MemoryRepository()
    dispatcher = RecordingDispatcher()
    service = JobService(repository, dispatcher)

    first = _run_immediate(service.submit(_submission(), "request-1"))
    replay = _run_immediate(service.submit(_submission(), "request-1"))

    assert first.created is True
    assert replay.created is False
    assert replay.job.id == first.job.id
    assert dispatcher.job_ids == [first.job.id]


def test_same_idempotency_key_rejects_changed_payload() -> None:
    service = JobService(MemoryRepository(), RecordingDispatcher())
    _run_immediate(service.submit(_submission(), "request-1"))

    with pytest.raises(IdempotencyConflictError):
        _run_immediate(service.submit(_submission(query="另一个请求"), "request-1"))


def test_queue_failure_is_persisted_as_failed_closed() -> None:
    repository = MemoryRepository()
    service = JobService(repository, RecordingDispatcher(ConnectionError("redis down")))

    with pytest.raises(JobDispatchError, match="could not be queued"):
        _run_immediate(service.submit(_submission(), "request-2"))

    assert repository.failed[0][1] == "queue_unavailable"
    assert "ConnectionError" in repository.failed[0][2]


def test_get_returns_persisted_job() -> None:
    repository = MemoryRepository()
    service = JobService(repository, RecordingDispatcher())
    created = _run_immediate(service.submit(_submission(), "request-3"))

    assert _run_immediate(service.get(created.job.id)) == created.job
    assert _run_immediate(service.get(uuid4())) is None


def test_get_trace_returns_auditable_job_envelope() -> None:
    repository = MemoryRepository()
    service = JobService(repository, RecordingDispatcher())
    created = _run_immediate(service.submit(_submission(), "trace-1"))

    trace = _run_immediate(service.get_trace(created.job.id))

    assert trace is not None
    assert trace.job.id == created.job.id
    assert trace.runs == []
    assert _run_immediate(service.get_trace(uuid4())) is None


def test_readiness_checks_database_and_queue() -> None:
    service = JobService(MemoryRepository(), RecordingDispatcher())

    assert _run_immediate(service.readiness()) == {"database": True, "queue": True}


def test_submission_rejects_duplicate_sample_ids() -> None:
    payload = _submission().model_dump(mode="json")
    payload["comments"].append(payload["comments"][0].copy())

    with pytest.raises(ValidationError, match="sample_id values must be unique"):
        JobSubmission.model_validate(payload)


def test_submit_redacts_sensitive_free_text_before_persistence() -> None:
    repository = MemoryRepository()
    service = JobService(repository, RecordingDispatcher())
    submission = _submission(query="联系 user@example.com，令牌 api_key=top-secret")

    created = _run_immediate(service.submit(submission, "redaction-1"))

    persisted = str(created.job.request_payload)
    assert "user@example.com" not in persisted
    assert "top-secret" not in persisted
    assert created.job.requested_by == "tester@example.com"


def test_submit_rejects_aggregate_request_over_budget() -> None:
    service = JobService(
        MemoryRepository(),
        RecordingDispatcher(),
        security_policy=SecurityPolicy(max_request_chars=50),
    )

    with pytest.raises(RequestBudgetExceeded):
        _run_immediate(service.submit(_submission(query="很长" * 100), "budget-1"))


def test_v2_routes_are_opt_in_and_v1_route_is_preserved() -> None:
    class FakeGraph:
        def invoke(self, state):
            return state

    base_app = create_app(lambda: FakeGraph())
    service = JobService(MemoryRepository(), RecordingDispatcher())
    v2_app = create_app(lambda: FakeGraph(), v2_job_service=service)

    base_paths = set(base_app.openapi()["paths"])
    v2_paths = set(v2_app.openapi()["paths"])
    assert "/v1/analyze" in base_paths
    assert "/v2/jobs" not in base_paths
    assert {
        "/v1/analyze",
        "/v2/jobs",
        "/v2/jobs/{job_id}",
        "/v2/jobs/{job_id}/trace",
    } <= v2_paths


def test_default_v2_service_is_disabled_without_durable_dependencies(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert build_v2_job_service() is None


def test_package_and_openapi_versions_match_project_metadata() -> None:
    class FakeGraph:
        def invoke(self, state):
            return state

    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == metadata["project"]["version"]
    assert create_app(lambda: FakeGraph()).openapi()["info"]["version"] == __version__


def test_default_v2_service_rejects_partial_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/opinion")
    monkeypatch.delenv("REDIS_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL and REDIS_URL together"):
        build_v2_job_service()


def test_default_v2_service_wires_postgres_and_arq(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/opinion")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ARQ_QUEUE_NAME", "test-queue")

    service = build_v2_job_service()

    assert service is not None
    assert service.repository.dsn == "postgresql://localhost/opinion"
    assert service.dispatcher.redis_url == "redis://localhost:6379/0"
    assert service.dispatcher.queue_name == "test-queue"
