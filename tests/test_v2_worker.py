import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.v2.contracts import (  # noqa: E402
    JobStatus,
    RunVersionSnapshot,
    VersionedComponent,
)
from opinion_agent.v2.jobs import ClaimedRun, JobRecord  # noqa: E402
from opinion_agent.v2.repository import (  # noqa: E402
    _retrieval_backend,
    _state_sha256,
    _token_totals,
    _tool_call_values,
)
from opinion_agent.v2.shadow import ShadowExecutor  # noqa: E402
from opinion_agent.v2.worker import (  # noqa: E402
    JobExecutor,
    build_version_snapshot,
    error_code,
    is_retryable_error,
)


def _run_immediate(coroutine):
    try:
        yielded = coroutine.send(None)
    except StopIteration as stop:
        return stop.value
    coroutine.close()
    raise AssertionError(f"fake coroutine unexpectedly suspended with {yielded!r}")


def _snapshot() -> RunVersionSnapshot:
    def component(name: str) -> VersionedComponent:
        return VersionedComponent(name=name, version="v1")

    return RunVersionSnapshot(
        model=component("model"),
        prompt=component("prompt"),
        toolset=component("tools"),
        policy=component("policy"),
    )


def _job(attempt_count: int = 1) -> JobRecord:
    now = datetime.now(timezone.utc)
    return JobRecord(
        id=uuid4(),
        project_id=UUID("11111111-1111-1111-1111-111111111111"),
        requested_by="tester",
        idempotency_key="worker-test",
        status="running",
        event_id="event-1",
        query="分析事件",
        request_payload={
            "comments": [{"sample_id": "c-1", "text": "评论"}],
        },
        attempt_count=attempt_count,
        created_at=now,
        started_at=now,
        updated_at=now,
    )


class FakeExecutionRepository:
    def __init__(self, claim: ClaimedRun | None) -> None:
        self.claim = claim
        self.finished = []
        self.failures = []
        self.claim_arguments = []

    async def claim_for_execution(
        self, job_id, snapshot, trace_id, worker_id, lease_seconds
    ):
        self.claim_arguments.append((job_id, worker_id, lease_seconds))
        if self.claim is None:
            return None
        return self.claim.model_copy(
            update={"trace_id": trace_id, "lease_owner": worker_id}
        )

    async def finish_execution(self, claim, result, status):
        self.finished.append((claim, result, status))

    async def record_execution_failure(
        self, claim, error_code, message, *, retryable, max_attempts
    ):
        status = (
            JobStatus.RETRYING
            if retryable and claim.job.attempt_count < max_attempts
            else JobStatus.FAILED_CLOSED
        )
        self.failures.append((error_code, message, retryable, max_attempts, status))
        return status


class FakeRunner:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.states = []

    async def invoke(self, state):
        self.states.append(state)
        if self.error:
            raise self.error
        return self.result


class FakeShadowSink:
    def __init__(self, error: Exception | None = None) -> None:
        self.records = []
        self.error = error

    async def record_shadow(self, record):
        if self.error:
            raise self.error
        self.records.append(record)


def _claim(attempt_count: int = 1) -> ClaimedRun:
    job = _job(attempt_count)
    return ClaimedRun(
        job=job,
        run_id=uuid4(),
        trace_id="initial",
        lease_owner="initial-worker",
        resume_state={
            "request_id": str(job.id),
            "event_id": job.event_id,
            "query": job.query,
            "comments": job.request_payload["comments"],
            "tool_traces": [],
            "errors": [],
        },
    )


def test_worker_completes_and_attaches_trace_identity() -> None:
    repository = FakeExecutionRepository(_claim())
    runner = FakeRunner(
        {
            "analysis_report": {"review_status": "llm_completed"},
            "tool_traces": [],
        }
    )
    executor = JobExecutor(
        repository,
        runner,
        _snapshot(),
        worker_id="worker-a",
        lease_seconds=90,
    )

    status = _run_immediate(executor.execute(repository.claim.job.id))

    assert status == JobStatus.COMPLETED
    assert repository.finished[0][2] == JobStatus.COMPLETED
    assert repository.finished[0][1]["trace_id"]
    assert repository.finished[0][1]["run_id"] == str(repository.claim.run_id)
    assert runner.states[0]["comments"][0]["sample_id"] == "c-1"
    assert repository.claim_arguments[0][1:] == ("worker-a", 90)


def test_worker_persists_manual_required_instead_of_false_success() -> None:
    repository = FakeExecutionRepository(_claim())
    runner = FakeRunner(
        {
            "analysis_report": {"review_status": "manual_required"},
            "tool_traces": [],
        }
    )

    status = _run_immediate(JobExecutor(repository, runner, _snapshot()).execute(_job().id))

    assert status == JobStatus.MANUAL_REQUIRED
    assert repository.finished[0][2] == JobStatus.MANUAL_REQUIRED


def test_worker_retries_transient_error_before_attempt_budget() -> None:
    repository = FakeExecutionRepository(_claim(attempt_count=1))
    runner = FakeRunner(error=TimeoutError("provider timed out"))

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot(), max_attempts=3).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.RETRYING
    assert repository.failures[0][0] == "provider_timeout"
    assert repository.failures[0][2] is True


def test_worker_fails_closed_when_retry_budget_is_exhausted() -> None:
    repository = FakeExecutionRepository(_claim(attempt_count=3))
    runner = FakeRunner(error=ConnectionError("provider unavailable"))

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot(), max_attempts=3).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.FAILED_CLOSED
    assert repository.failures[0][0] == "provider_connection_error"


def test_worker_does_not_execute_a_job_that_was_not_claimed() -> None:
    repository = FakeExecutionRepository(None)
    runner = FakeRunner(result={})

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot()).execute(uuid4())
    )

    assert status is None
    assert runner.states == []


def test_invalid_output_contract_fails_closed_without_retry() -> None:
    repository = FakeExecutionRepository(_claim())
    runner = FakeRunner(result={"tool_traces": []})

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot()).execute(repository.claim.job.id)
    )

    assert status == JobStatus.FAILED_CLOSED
    assert repository.failures[0][0] == "output_contract_error"
    assert repository.failures[0][2] is False


def test_unknown_tool_trace_fails_closed_without_retry() -> None:
    repository = FakeExecutionRepository(_claim())
    runner = FakeRunner(
        result={
            "analysis_report": {"review_status": "not_required"},
            "tool_traces": [{"node": "delete_everything"}],
        }
    )

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot()).execute(repository.claim.job.id)
    )

    assert status == JobStatus.FAILED_CLOSED
    assert repository.failures[0][0] == "security_policy_violation"
    assert repository.failures[0][2] is False


def test_worker_redacts_sensitive_output_before_persistence() -> None:
    repository = FakeExecutionRepository(_claim())
    runner = FakeRunner(
        result={
            "analysis_report": {
                "review_status": "not_required",
                "executive_summary": "联系 analyst@example.com",
            },
            "tool_traces": [],
        }
    )

    status = _run_immediate(
        JobExecutor(repository, runner, _snapshot()).execute(repository.claim.job.id)
    )

    assert status == JobStatus.COMPLETED
    assert "analyst@example.com" not in str(repository.finished[0][1])


def test_failure_policy_covers_429_5xx_and_invalid_json() -> None:
    class ProviderError(RuntimeError):
        def __init__(self, status_code):
            self.status_code = status_code

    invalid_json = json.JSONDecodeError("bad json", "{", 1)
    assert is_retryable_error(ProviderError(429))
    assert error_code(ProviderError(429)) == "provider_rate_limited"
    assert is_retryable_error(ProviderError(503))
    assert error_code(ProviderError(503)) == "provider_server_error"
    assert is_retryable_error(invalid_json)
    assert error_code(invalid_json) == "provider_invalid_json"


def test_version_snapshot_does_not_persist_credentials(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "super-secret")
    monkeypatch.setenv("LLM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen-test")

    serialized = json.dumps(build_version_snapshot().model_dump(mode="json"))

    assert "super-secret" not in serialized
    assert "provider.example" not in serialized
    assert "qwen-test" in serialized


def test_trace_helpers_preserve_tokens_backend_and_duration() -> None:
    traces = [
        {
            "node": "evidence_retriever",
            "status": "ok",
            "duration_ms": 12.5,
            "details": {
                "backend": "hybrid_bge_tfidf",
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        }
    ]

    assert _token_totals(traces) == (10, 4)
    assert _retrieval_backend(traces) == "hybrid_bge_tfidf"
    values = _tool_call_values(uuid4(), 1, traces[0], datetime.now(timezone.utc))
    assert values[5] == "succeeded"
    assert values[9] == 12.5
    assert values[10:12] == (10, 4)


def test_checkpoint_hash_is_canonical_and_detects_tampering() -> None:
    first = {"event_id": "event-1", "comments": [{"text": "评论"}]}
    reordered = {"comments": [{"text": "评论"}], "event_id": "event-1"}
    tampered = {"event_id": "event-1", "comments": [{"text": "已修改"}]}

    assert _state_sha256(first) == _state_sha256(reordered)
    assert _state_sha256(first) != _state_sha256(tampered)


def test_shadow_is_disabled_by_default() -> None:
    repository = FakeExecutionRepository(_claim())
    official = FakeRunner(
        {"analysis_report": {"review_status": "not_required"}, "tool_traces": []}
    )
    unused_candidate = FakeRunner(error=AssertionError("shadow must not run"))

    status = _run_immediate(
        JobExecutor(repository, official, _snapshot()).execute(repository.claim.job.id)
    )

    assert status == JobStatus.COMPLETED
    assert unused_candidate.states == []


def test_shadow_success_uses_copy_and_cannot_replace_official_result() -> None:
    repository = FakeExecutionRepository(_claim())
    official_result = {
        "analysis_report": {"review_status": "not_required", "source": "official"},
        "tool_traces": [],
    }
    official = FakeRunner(official_result)
    sink = FakeShadowSink()

    class MutatingCandidate:
        async def invoke(self, state):
            state["query"] = "shadow-mutated"
            return {
                "analysis_report": {"review_status": "not_required", "source": "shadow"},
                "tool_traces": [],
            }

    shadow = ShadowExecutor(
        MutatingCandidate(), sink, candidate_name="runtime-v1", timeout_seconds=1
    )
    status = asyncio.run(
        JobExecutor(repository, official, _snapshot(), shadow=shadow).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.COMPLETED
    assert repository.finished[0][1]["analysis_report"]["source"] == "official"
    assert official.states[0]["query"] == "分析事件"
    assert sink.records[0].status == "succeeded"
    assert sink.records[0].result_payload["analysis_report"]["source"] == "shadow"


def test_shadow_failure_and_sink_failure_do_not_change_official_status() -> None:
    repository = FakeExecutionRepository(_claim())
    official = FakeRunner(
        {"analysis_report": {"review_status": "not_required"}, "tool_traces": []}
    )
    sink = FakeShadowSink(error=RuntimeError("shadow store unavailable"))
    shadow = ShadowExecutor(
        FakeRunner(error=RuntimeError("candidate failed")),
        sink,
        candidate_name="runtime-v1",
        timeout_seconds=1,
    )

    status = asyncio.run(
        JobExecutor(repository, official, _snapshot(), shadow=shadow).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.COMPLETED
    assert repository.finished[0][2] == JobStatus.COMPLETED


def test_shadow_failure_record_redacts_sensitive_error() -> None:
    repository = FakeExecutionRepository(_claim())
    official = FakeRunner(
        {"analysis_report": {"review_status": "not_required"}, "tool_traces": []}
    )
    sink = FakeShadowSink()
    shadow = ShadowExecutor(
        FakeRunner(error=RuntimeError("api_key=top-secret")),
        sink,
        candidate_name="runtime-v1",
        timeout_seconds=1,
    )

    status = asyncio.run(
        JobExecutor(repository, official, _snapshot(), shadow=shadow).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.COMPLETED
    assert sink.records[0].status == "failed"
    assert "top-secret" not in sink.records[0].error_message
    assert "[REDACTED]" in sink.records[0].error_message


def test_shadow_start_failure_does_not_change_official_status() -> None:
    repository = FakeExecutionRepository(_claim())
    official = FakeRunner(
        {"analysis_report": {"review_status": "not_required"}, "tool_traces": []}
    )

    class BrokenShadow:
        def start(self, claim, state):
            raise RuntimeError("could not copy shadow input")

        async def observe(self, task):
            raise AssertionError("observe must not run when shadow start failed")

    status = asyncio.run(
        JobExecutor(
            repository,
            official,
            _snapshot(),
            shadow=BrokenShadow(),  # type: ignore[arg-type]
        ).execute(repository.claim.job.id)
    )

    assert status == JobStatus.COMPLETED
    assert repository.finished[0][2] == JobStatus.COMPLETED


def test_shadow_timeout_is_recorded_without_changing_official_status() -> None:
    repository = FakeExecutionRepository(_claim())
    official = FakeRunner(
        {"analysis_report": {"review_status": "not_required"}, "tool_traces": []}
    )
    sink = FakeShadowSink()

    class SlowCandidate:
        async def invoke(self, state):
            await asyncio.sleep(0.05)
            return {}

    shadow = ShadowExecutor(
        SlowCandidate(), sink, candidate_name="runtime-v1", timeout_seconds=0.001
    )
    status = asyncio.run(
        JobExecutor(repository, official, _snapshot(), shadow=shadow).execute(
            repository.claim.job.id
        )
    )

    assert status == JobStatus.COMPLETED
    assert sink.records[0].status == "timed_out"
    assert sink.records[0].result_payload is None
