"""Queue-independent worker execution and failure policy."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Protocol
from uuid import UUID, uuid4

from opinion_agent.agent.reviewer import REVIEW_PROMPT_VERSION
from opinion_agent.governance import SecurityPolicy, SecurityPolicyError, redact_sensitive
from opinion_agent.observability import log_event

from .contracts import JobStatus, RunVersionSnapshot, VersionedComponent
from .jobs import ClaimedRun, JobRepository
from .shadow import ShadowExecutor


LOGGER = logging.getLogger(__name__)


class AgentRunner(Protocol):
    async def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


class ThreadedGraphRunner:
    """Run the existing synchronous graph outside ARQ's event loop."""

    def __init__(self, graph_provider) -> None:
        self.graph_provider = graph_provider

    async def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        graph = await asyncio.to_thread(self.graph_provider)
        return await asyncio.to_thread(graph.invoke, state)


class LeaseLostError(RuntimeError):
    """The worker no longer owns the durable execution lease."""


class JobExecutor:
    def __init__(
        self,
        repository: JobRepository,
        runner: AgentRunner,
        snapshot: RunVersionSnapshot,
        *,
        max_attempts: int = 3,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: float = 0,
        security_policy: SecurityPolicy | None = None,
        shadow: ShadowExecutor | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.repository = repository
        self.runner = runner
        self.snapshot = snapshot
        self.max_attempts = max_attempts
        self.worker_id = worker_id or f"worker-{uuid4().hex}"
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        if heartbeat_interval_seconds < 0:
            raise ValueError("heartbeat_interval_seconds must not be negative")
        if heartbeat_interval_seconds and heartbeat_interval_seconds >= lease_seconds:
            raise ValueError("heartbeat interval must be shorter than the lease")
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.security_policy = security_policy or SecurityPolicy.from_env()
        self.shadow = shadow

    async def execute(self, job_id: UUID) -> JobStatus | None:
        trace_id = uuid4().hex
        claim = await self.repository.claim_for_execution(
            job_id,
            self.snapshot,
            trace_id,
            self.worker_id,
            self.lease_seconds,
        )
        if claim is None:
            return None

        log_event(
            LOGGER,
            "job_claimed",
            job_id=claim.job.id,
            run_id=claim.run_id,
            trace_id=claim.trace_id,
            attempt=claim.job.attempt_count,
            worker_id=claim.lease_owner,
        )

        state = _graph_input(claim)
        shadow_task = None
        if self.shadow is not None:
            try:
                shadow_task = self.shadow.start(claim, state)
            except Exception as exc:
                log_event(
                    LOGGER,
                    "shadow_start_failed",
                    job_id=claim.job.id,
                    run_id=claim.run_id,
                    trace_id=claim.trace_id,
                    error_type=type(exc).__name__,
                    error_message=redact_sensitive(str(exc))[:500],
                )
        try:
            result = await self._invoke_with_heartbeat(claim, state)
            if not isinstance(result, dict):
                raise TypeError("agent graph result must be a dictionary")
            result = redact_sensitive(result)
            self.security_policy.validate_result(result)
            status = _result_status(result)
            result = {**result, "trace_id": claim.trace_id, "run_id": str(claim.run_id)}
            await self.repository.finish_execution(claim, result, status)
            log_event(
                LOGGER,
                "job_finished",
                job_id=claim.job.id,
                run_id=claim.run_id,
                trace_id=claim.trace_id,
                status=status.value,
            )
            return status
        except LeaseLostError:
            # Another recovery actor now owns the state transition. Do not let
            # this stale worker overwrite it; ask ARQ to redeliver instead.
            log_event(
                LOGGER,
                "job_lease_lost",
                job_id=claim.job.id,
                run_id=claim.run_id,
                trace_id=claim.trace_id,
            )
            return JobStatus.RETRYING
        except Exception as exc:
            retryable = is_retryable_error(exc)
            status = await self.repository.record_execution_failure(
                claim,
                error_code=error_code(exc),
                message=f"{type(exc).__name__}: {str(exc)[:500]}",
                retryable=retryable,
                max_attempts=self.max_attempts,
            )
            log_event(
                LOGGER,
                "job_execution_failed",
                job_id=claim.job.id,
                run_id=claim.run_id,
                trace_id=claim.trace_id,
                error_code=error_code(exc),
                retryable=retryable,
                status=status.value,
            )
            return status
        finally:
            if shadow_task is not None:
                await self.shadow.observe(shadow_task)

    async def _invoke_with_heartbeat(
        self,
        claim: ClaimedRun,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.heartbeat_interval_seconds:
            return await self.runner.invoke(state)

        work = asyncio.create_task(self.runner.invoke(state))
        heartbeat = asyncio.create_task(self._heartbeat_loop(claim))
        try:
            done, _ = await asyncio.wait(
                {work, heartbeat},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done and heartbeat.exception() is not None:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                raise heartbeat.exception()  # type: ignore[misc]
            return await work
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat_loop(self, claim: ClaimedRun) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            renewed = await self.repository.heartbeat(claim, self.lease_seconds)
            if not renewed:
                raise LeaseLostError("worker execution lease was lost")


def _graph_input(claim: ClaimedRun) -> dict[str, Any]:
    return dict(claim.resume_state)


def _result_status(result: dict[str, Any]) -> JobStatus:
    report = result.get("analysis_report")
    if not isinstance(report, dict):
        raise ValueError("agent output contract violation: analysis_report is missing")
    review_status = report.get("review_status")
    if review_status in {"manual_required", "llm_failed"}:
        return JobStatus.MANUAL_REQUIRED
    if review_status not in {"not_required", "human_completed", "llm_completed"}:
        raise ValueError(
            f"agent output contract violation: unknown review_status={review_status!r}"
        )
    return JobStatus.COMPLETED


def is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, json.JSONDecodeError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code == 429 or (
        isinstance(status_code, int) and 500 <= status_code <= 599
    )


def error_code(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return "provider_rate_limited"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "provider_server_error"
    if isinstance(exc, TimeoutError):
        return "provider_timeout"
    if isinstance(exc, ConnectionError):
        return "provider_connection_error"
    if isinstance(exc, json.JSONDecodeError):
        return "provider_invalid_json"
    if isinstance(exc, LeaseLostError):
        return "worker_lease_lost"
    if isinstance(exc, SecurityPolicyError):
        return "security_policy_violation"
    if isinstance(exc, (TypeError, ValueError)):
        return "output_contract_error"
    return "unhandled_execution_error"


def build_version_snapshot() -> RunVersionSnapshot:
    """Capture public executable identity without persisting credentials."""

    llm_model = os.getenv("LLM_MODEL", "offline_or_unconfigured")
    sentiment_backend = os.getenv("SENTIMENT_BACKEND", "legacy_xgboost")
    retriever_backend = os.getenv("RETRIEVER_BACKEND", "hybrid")
    security_policy = SecurityPolicy.from_env()
    return RunVersionSnapshot(
        model=VersionedComponent(
            name=llm_model,
            version=os.getenv("MODEL_VERSION", "runtime-config-v1"),
            config={
                "sentiment_backend": sentiment_backend,
                "reviewer_enabled": all(
                    os.getenv(name)
                    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")
                ),
            },
        ),
        prompt=VersionedComponent(
            name="event_stance_review",
            version=REVIEW_PROMPT_VERSION,
        ),
        toolset=VersionedComponent(
            name="opinion_agent_graph",
            version=os.getenv("TOOLSET_VERSION", "v2-job-worker-1"),
            config={
                "retriever_backend": retriever_backend,
                "retrieval_min_score": os.getenv("RETRIEVAL_MIN_SCORE", "0.04"),
            },
        ),
        policy=VersionedComponent(
            name="event_aware_review_gate",
            version=os.getenv("POLICY_VERSION", "event_aware_cascade_v1"),
            config={
                "max_attempts": int(os.getenv("JOB_MAX_ATTEMPTS", "3")),
                **security_policy.snapshot(),
            },
        ),
    )
