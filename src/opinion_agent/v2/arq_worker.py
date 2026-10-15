"""ARQ entrypoint: ``arq opinion_agent.v2.arq_worker.WorkerSettings``."""

from __future__ import annotations

import os
from uuid import UUID

from arq import Retry
from arq.connections import RedisSettings

from opinion_agent.api import get_default_graph

from .contracts import JobStatus
from .repository import PsycopgJobRepository
from .shadow import RuntimeAdapterShadowRunner, ShadowExecutor
from .shadow_repository import PsycopgShadowSink
from .worker import JobExecutor, ThreadedGraphRunner, build_version_snapshot


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required to start the V2 worker")
    return value


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off"
    )


def _load_runtime_adapter():
    try:
        from agent_runtime_platform.adapters import OpinionAgentRuntimeAdapter
    except ImportError as exc:  # pragma: no cover - depends on shadow extra
        raise RuntimeError(
            "Runtime shadow requires the pinned 'shadow' optional dependency"
        ) from exc
    return OpinionAgentRuntimeAdapter


def _build_shadow_executor(database_url: str) -> ShadowExecutor | None:
    if not _env_flag("RUNTIME_SHADOW_ENABLED"):
        return None

    adapter_type = _load_runtime_adapter()
    adapter = adapter_type(
        graph_provider=get_default_graph,
        checkpoint_path=os.getenv(
            "RUNTIME_SHADOW_CHECKPOINT_PATH",
            "/tmp/opinion-agent-shadow/runtime.sqlite3",
        ),
        lease_ttl_seconds=float(os.getenv("RUNTIME_SHADOW_LEASE_SECONDS", "60")),
        owner_id=os.getenv("WORKER_ID") or None,
    )
    return ShadowExecutor(
        RuntimeAdapterShadowRunner(adapter),
        PsycopgShadowSink(database_url),
        candidate_name=os.getenv(
            "RUNTIME_SHADOW_CANDIDATE",
            "agent-runtime-quality-platform@0.5.2.dev0",
        ),
        timeout_seconds=float(os.getenv("RUNTIME_SHADOW_TIMEOUT_SECONDS", "120")),
    )


async def startup(ctx: dict) -> None:
    database_url = _required_env("DATABASE_URL")
    repository = PsycopgJobRepository(database_url)
    max_attempts = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
    ctx["recovered_jobs"] = await repository.recover_stale_jobs(max_attempts)
    ctx["executor"] = JobExecutor(
        repository,
        ThreadedGraphRunner(get_default_graph),
        build_version_snapshot(),
        max_attempts=max_attempts,
        worker_id=os.getenv("WORKER_ID") or None,
        lease_seconds=int(os.getenv("JOB_LEASE_SECONDS", "60")),
        heartbeat_interval_seconds=float(
            os.getenv("JOB_HEARTBEAT_INTERVAL_SECONDS", "20")
        ),
        shadow=_build_shadow_executor(database_url),
    )


async def run_analysis_job(ctx: dict, job_id: str) -> str:
    status = await ctx["executor"].execute(UUID(job_id))
    if status == JobStatus.RETRYING:
        raise Retry(defer=int(os.getenv("JOB_RETRY_DELAY_SECONDS", "5")))
    return status.value if status is not None else "not_claimed"


class WorkerSettings:
    functions = [run_analysis_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(_required_env("REDIS_URL"))
    queue_name = os.getenv("ARQ_QUEUE_NAME", "opinion-agent")
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "2"))
    job_timeout = int(os.getenv("ARQ_JOB_TIMEOUT_SECONDS", "300"))
