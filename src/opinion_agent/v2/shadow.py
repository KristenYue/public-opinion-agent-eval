"""Failure-isolated shadow execution boundary for V2 worker candidates."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID

from opinion_agent.governance import redact_sensitive
from opinion_agent.observability import log_event

from .jobs import ClaimedRun


LOGGER = logging.getLogger(__name__)


class ShadowRunner(Protocol):
    async def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ShadowRecord:
    job_id: UUID
    official_run_id: UUID
    trace_id: str
    candidate_name: str
    status: Literal["succeeded", "failed", "timed_out"]
    duration_ms: float
    result_payload: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


class ShadowSink(Protocol):
    async def record_shadow(self, record: ShadowRecord) -> None: ...


class RuntimeAdapter(Protocol):
    async def analyze(
        self, request: dict[str, Any], *, task_id: str | None = None
    ) -> Any: ...


class RuntimeAdapterShadowRunner:
    """Translate V2 graph state into the Runtime Platform adapter contract."""

    def __init__(self, adapter: RuntimeAdapter) -> None:
        self.adapter = adapter

    async def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        request = {
            "event_id": state["event_id"],
            "query": state["query"],
            "comments": state["comments"],
        }
        runtime_result = await self.adapter.analyze(
            request,
            task_id=f"{state['request_id']}:shadow",
        )
        status = getattr(runtime_result.status, "value", runtime_result.status)
        if status != "completed":
            raise RuntimeError(f"runtime shadow finished with status={status!r}")
        result = runtime_result.result
        if not isinstance(result, dict):
            raise TypeError("runtime shadow completed without a dictionary result")
        return result


class ShadowExecutor:
    """Run a candidate without allowing it to affect the official result."""

    def __init__(
        self,
        runner: ShadowRunner,
        sink: ShadowSink,
        *,
        candidate_name: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not candidate_name.strip():
            raise ValueError("shadow candidate_name must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("shadow timeout_seconds must be positive")
        self.runner = runner
        self.sink = sink
        self.candidate_name = candidate_name
        self.timeout_seconds = timeout_seconds

    def start(
        self, claim: ClaimedRun, state: dict[str, Any]
    ) -> asyncio.Task[ShadowRecord]:
        return asyncio.create_task(self._execute(claim, deepcopy(state)))

    async def observe(self, task: asyncio.Task[ShadowRecord]) -> None:
        """Wait for bounded shadow work; candidate/sink failures are contained."""
        try:
            await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive containment around custom sinks
            log_event(
                LOGGER,
                "shadow_observer_failed",
                error_type=type(exc).__name__,
                error_message=str(exc)[:500],
            )

    async def _execute(
        self, claim: ClaimedRun, state: dict[str, Any]
    ) -> ShadowRecord:
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                self.runner.invoke(state),
                timeout=self.timeout_seconds,
            )
            if not isinstance(result, dict):
                raise TypeError("shadow candidate result must be a dictionary")
            record = ShadowRecord(
                job_id=claim.job.id,
                official_run_id=claim.run_id,
                trace_id=claim.trace_id,
                candidate_name=self.candidate_name,
                status="succeeded",
                duration_ms=(perf_counter() - started) * 1000,
                result_payload=redact_sensitive(result),
            )
        except TimeoutError as exc:
            record = ShadowRecord(
                job_id=claim.job.id,
                official_run_id=claim.run_id,
                trace_id=claim.trace_id,
                candidate_name=self.candidate_name,
                status="timed_out",
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
                error_message="shadow candidate exceeded its isolated timeout",
            )
        except Exception as exc:
            record = ShadowRecord(
                job_id=claim.job.id,
                official_run_id=claim.run_id,
                trace_id=claim.trace_id,
                candidate_name=self.candidate_name,
                status="failed",
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
                error_message=redact_sensitive(str(exc))[:500],
            )

        try:
            await self.sink.record_shadow(record)
        except Exception as exc:
            log_event(
                LOGGER,
                "shadow_sink_failed",
                job_id=claim.job.id,
                run_id=claim.run_id,
                trace_id=claim.trace_id,
                candidate_name=self.candidate_name,
                error_type=type(exc).__name__,
                error_message=redact_sensitive(str(exc))[:500],
            )
        return record
