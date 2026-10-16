"""PostgreSQL implementation of the V2 job repository."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from .jobs import (
    AgentRunTrace,
    CheckpointRecord,
    ClaimedRun,
    CreateJobResult,
    HumanReviewRecord,
    IdempotencyConflictError,
    JobRecord,
    JobSubmission,
    JobTrace,
    ShadowRunRecord,
    ToolCallRecord,
    canonical_payload_hash,
)
from .contracts import JobStatus, RunVersionSnapshot, VersionedComponent


JOB_COLUMNS = """
    id, project_id, requested_by, idempotency_key, status, event_id, query,
    request_payload, result_payload, error_code, error_message, attempt_count,
    created_at, started_at, finished_at, updated_at, lease_owner,
    lease_expires_at, last_heartbeat_at, recovery_count
"""


def _load_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - depends on production extra
        raise RuntimeError(
            "PostgreSQL support requires: pip install -e '.[production]'"
        ) from exc
    return psycopg, dict_row


def _job_record(row: dict[str, Any]) -> JobRecord:
    payload = row.get("request_payload")
    result = row.get("result_payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(result, str):
        result = json.loads(result)
    return JobRecord.model_validate(
        {**row, "request_payload": payload, "result_payload": result}
    )


def _json_fields(row: dict[str, Any], *names: str) -> dict[str, Any]:
    """Copy a database row and decode JSON values for driver compatibility."""

    normalized = dict(row)
    for name in names:
        value = normalized.get(name)
        if isinstance(value, str):
            normalized[name] = json.loads(value)
    return normalized


class PsycopgJobRepository:
    """Transaction boundary used by the API before worker execution."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("database DSN must not be blank")
        self.dsn = dsn

    async def _connect(self):
        psycopg, dict_row = _load_psycopg()
        return await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row)

    async def ping(self) -> bool:
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                row = await cursor.fetchone()
        return bool(row)

    async def create_or_get(
        self,
        submission: JobSubmission,
        idempotency_key: str,
    ) -> CreateJobResult:
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 200:
            raise ValueError("Idempotency-Key must contain 1 to 200 characters")

        payload = submission.replay_payload()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        now = datetime.now(timezone.utc)
        job_id = uuid4()
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    INSERT INTO analysis_jobs (
                        id, project_id, requested_by, idempotency_key, status,
                        event_id, query, request_payload, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, 'queued', %s, %s, %s::jsonb, %s, %s
                    )
                    ON CONFLICT (project_id, idempotency_key) DO NOTHING
                    RETURNING {JOB_COLUMNS}
                    """,
                    (
                        job_id,
                        submission.project_id,
                        submission.requested_by,
                        normalized_key,
                        submission.event_id,
                        submission.query,
                        payload_json,
                        now,
                        now,
                    ),
                )
                row = await cursor.fetchone()
                created = row is not None
                if row is None:
                    await cursor.execute(
                        f"""
                        SELECT {JOB_COLUMNS}
                        FROM analysis_jobs
                        WHERE project_id = %s AND idempotency_key = %s
                        """,
                        (submission.project_id, normalized_key),
                    )
                    row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("idempotent job lookup returned no row")

                job = _job_record(row)
                if canonical_payload_hash(job.request_payload) != canonical_payload_hash(payload):
                    raise IdempotencyConflictError(
                        "Idempotency-Key was already used for a different request"
                    )

                if created:
                    for comment in submission.comments:
                        comment_payload = comment.model_dump(exclude_none=True)
                        input_hash = hashlib.sha256(
                            json.dumps(
                                comment_payload,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        await cursor.execute(
                            """
                            INSERT INTO comments (
                                id, job_id, sample_id, text, context, source_url,
                                input_sha256
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                uuid4(),
                                job.id,
                                comment.sample_id,
                                comment.text,
                                comment.context,
                                comment.source_url,
                                input_hash,
                            ),
                        )
            await connection.commit()
        return CreateJobResult(job=job, created=created)

    async def get(self, job_id: UUID) -> JobRecord | None:
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {JOB_COLUMNS} FROM analysis_jobs WHERE id = %s",
                    (job_id,),
                )
                row = await cursor.fetchone()
        return _job_record(row) if row else None

    async def get_project_role(self, project_id: UUID, subject: str) -> str | None:
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT role
                    FROM project_members
                    WHERE project_id = %s AND subject = %s
                    """,
                    (project_id, subject),
                )
                row = await cursor.fetchone()
        return str(row["role"]) if row else None

    async def get_trace(self, job_id: UUID) -> JobTrace | None:
        """Load the durable execution ledger for one job in deterministic order."""

        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"SELECT {JOB_COLUMNS} FROM analysis_jobs WHERE id = %s",
                    (job_id,),
                )
                job_row = await cursor.fetchone()
                if job_row is None:
                    return None

                await cursor.execute(
                    """
                    SELECT id, trace_id, attempt, status, version_snapshot,
                           input_state, output_state, token_input, token_output,
                           worker_id, heartbeat_at, recovery_reason,
                           started_at, finished_at
                    FROM agent_runs
                    WHERE job_id = %s
                    ORDER BY attempt ASC
                    """,
                    (job_id,),
                )
                run_rows = await cursor.fetchall()
                run_ids = [row["id"] for row in run_rows]

                checkpoint_rows: list[dict[str, Any]] = []
                tool_rows: list[dict[str, Any]] = []
                if run_ids:
                    await cursor.execute(
                        """
                        SELECT id, run_id, sequence_no, checkpoint_kind,
                               node_name, state, state_sha256, created_at
                        FROM run_checkpoints
                        WHERE run_id = ANY(%s)
                        ORDER BY run_id, sequence_no ASC
                        """,
                        (run_ids,),
                    )
                    checkpoint_rows = await cursor.fetchall()
                    await cursor.execute(
                        """
                        SELECT id, run_id, sequence_no, node_name, tool_name,
                               status, request_payload, response_payload,
                               error_type, duration_ms, token_input, token_output,
                               started_at, finished_at
                        FROM tool_calls
                        WHERE run_id = ANY(%s)
                        ORDER BY run_id, sequence_no ASC
                        """,
                        (run_ids,),
                    )
                    tool_rows = await cursor.fetchall()

                await cursor.execute(
                    """
                    SELECT id, run_id, comment_id, reviewer_id, previous_label,
                           final_label, rationale, submitted_at
                    FROM human_reviews
                    WHERE job_id = %s
                    ORDER BY submitted_at ASC, id ASC
                    """,
                    (job_id,),
                )
                review_rows = await cursor.fetchall()
                await cursor.execute(
                    """
                    SELECT id, official_run_id, trace_id, candidate_name,
                           status, duration_ms, result_payload, error_type,
                           error_message, created_at
                    FROM shadow_runs
                    WHERE job_id = %s
                    ORDER BY created_at ASC, id ASC
                    """,
                    (job_id,),
                )
                shadow_rows = await cursor.fetchall()

        checkpoints_by_run: dict[UUID, list[CheckpointRecord]] = {}
        for row in checkpoint_rows:
            normalized = dict(row)
            run_id = normalized.pop("run_id")
            checkpoints_by_run.setdefault(run_id, []).append(
                CheckpointRecord.model_validate(_json_fields(normalized, "state"))
            )
        tools_by_run: dict[UUID, list[ToolCallRecord]] = {}
        for row in tool_rows:
            normalized = dict(row)
            run_id = normalized.pop("run_id")
            tools_by_run.setdefault(run_id, []).append(
                ToolCallRecord.model_validate(
                    _json_fields(normalized, "request_payload", "response_payload")
                )
            )

        runs = []
        for row in run_rows:
            normalized = _json_fields(
                row, "version_snapshot", "input_state", "output_state"
            )
            run_id = normalized["id"]
            runs.append(
                AgentRunTrace.model_validate(
                    {
                        **normalized,
                        "checkpoints": checkpoints_by_run.get(run_id, []),
                        "tool_calls": tools_by_run.get(run_id, []),
                    }
                )
            )
        return JobTrace(
            job=_job_record(job_row),
            runs=runs,
            human_reviews=[HumanReviewRecord.model_validate(row) for row in review_rows],
            shadow_runs=[
                ShadowRunRecord.model_validate(_json_fields(row, "result_payload"))
                for row in shadow_rows
            ],
        )

    async def fail_queued_job(
        self, job_id: UUID, error_code: str, message: str
    ) -> None:
        now = datetime.now(timezone.utc)
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = 'failed_closed', error_code = %s,
                        error_message = %s, finished_at = %s, updated_at = %s
                    WHERE id = %s AND status = 'queued'
                    """,
                    (error_code, message, now, now, job_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("queued job could not be marked failed_closed")
            await connection.commit()

    async def _ensure_component(
        self,
        cursor,
        kind: str,
        component: VersionedComponent,
    ) -> UUID:
        component_id = uuid4()
        await cursor.execute(
            """
            INSERT INTO model_versions (
                id, component_kind, name, version, config, config_sha256
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (component_kind, name, version, config_sha256)
            DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (
                component_id,
                kind,
                component.name,
                component.version,
                json.dumps(component.config, ensure_ascii=False, sort_keys=True),
                component.resolved_hash(),
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError(f"failed to resolve {kind} version")
        return row["id"]

    async def claim_for_execution(
        self,
        job_id: UUID,
        snapshot: RunVersionSnapshot,
        trace_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> ClaimedRun | None:
        """Atomically claim one queued/retrying job and create its run ledger."""

        now = datetime.now(timezone.utc)
        run_id = uuid4()
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    f"""
                    UPDATE analysis_jobs
                    SET status = 'running',
                        attempt_count = attempt_count + 1,
                        started_at = COALESCE(started_at, %s),
                        updated_at = %s,
                        lease_owner = %s,
                        lease_expires_at = %s + (%s * INTERVAL '1 second'),
                        last_heartbeat_at = %s,
                        error_code = NULL,
                        error_message = NULL
                    WHERE id = %s AND status IN ('queued', 'retrying')
                    RETURNING {JOB_COLUMNS}
                    """,
                    (now, now, worker_id, now, lease_seconds, now, job_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    await connection.rollback()
                    return None
                job = _job_record(row)

                input_state = _graph_input(job)
                if job.attempt_count > 1:
                    await cursor.execute(
                        """
                        SELECT checkpoint.state, checkpoint.state_sha256
                        FROM run_checkpoints AS checkpoint
                        JOIN agent_runs AS previous_run
                          ON previous_run.id = checkpoint.run_id
                        WHERE previous_run.job_id = %s
                          AND checkpoint.checkpoint_kind = 'input_replay'
                        ORDER BY previous_run.attempt DESC
                        LIMIT 1
                        """,
                        (job.id,),
                    )
                    checkpoint_row = await cursor.fetchone()
                    if checkpoint_row is None:
                        raise RuntimeError("retrying job has no input replay checkpoint")
                    checkpoint_state = checkpoint_row["state"]
                    if isinstance(checkpoint_state, str):
                        checkpoint_state = json.loads(checkpoint_state)
                    if _state_sha256(checkpoint_state) != checkpoint_row["state_sha256"]:
                        raise RuntimeError("input replay checkpoint hash mismatch")
                    input_state = checkpoint_state

                version_ids = {}
                for kind, component in (
                    ("model", snapshot.model),
                    ("prompt", snapshot.prompt),
                    ("toolset", snapshot.toolset),
                    ("policy", snapshot.policy),
                ):
                    version_ids[kind] = await self._ensure_component(
                        cursor, kind, component
                    )

                await cursor.execute(
                    """
                    INSERT INTO agent_runs (
                        id, job_id, trace_id, attempt, status,
                        model_version_id, prompt_version_id,
                        toolset_version_id, policy_version_id,
                        version_snapshot, input_state, started_at
                    ) VALUES (
                        %s, %s, %s, %s, 'running', %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s
                    )
                    """,
                    (
                        run_id,
                        job.id,
                        trace_id,
                        job.attempt_count,
                        version_ids["model"],
                        version_ids["prompt"],
                        version_ids["toolset"],
                        version_ids["policy"],
                        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
                        json.dumps(input_state, ensure_ascii=False),
                        now,
                    ),
                )
                await cursor.execute(
                    """
                    UPDATE agent_runs
                    SET worker_id = %s, heartbeat_at = %s
                    WHERE id = %s
                    """,
                    (worker_id, now, run_id),
                )
                await _insert_checkpoint(
                    cursor,
                    run_id,
                    0,
                    "input_replay",
                    "__input__",
                    input_state,
                )
            await connection.commit()
        return ClaimedRun(
            job=job,
            run_id=run_id,
            trace_id=trace_id,
            lease_owner=worker_id,
            resume_state=input_state,
        )

    async def heartbeat(self, claim: ClaimedRun, lease_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET last_heartbeat_at = %s,
                        lease_expires_at = %s + (%s * INTERVAL '1 second'),
                        updated_at = %s
                    WHERE id = %s AND status = 'running' AND lease_owner = %s
                    """,
                    (
                        now,
                        now,
                        lease_seconds,
                        now,
                        claim.job.id,
                        claim.lease_owner,
                    ),
                )
                renewed = cursor.rowcount == 1
                if renewed:
                    await cursor.execute(
                        """
                        UPDATE agent_runs SET heartbeat_at = %s
                        WHERE id = %s AND status = 'running' AND worker_id = %s
                        """,
                        (now, claim.run_id, claim.lease_owner),
                    )
            await connection.commit()
        return renewed

    async def finish_execution(
        self,
        claim: ClaimedRun,
        result: dict[str, Any],
        status: JobStatus,
    ) -> None:
        if status not in {JobStatus.COMPLETED, JobStatus.MANUAL_REQUIRED}:
            raise ValueError("successful execution must complete or require manual review")
        now = datetime.now(timezone.utc)
        output_json = json.dumps(result, ensure_ascii=False, default=str)
        traces = list(result.get("tool_traces") or [])
        evidence = list(result.get("retrieved_evidence") or [])
        token_input, token_output = _token_totals(traces)
        retrieval_backend = _retrieval_backend(traces)

        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s, output_state = %s::jsonb,
                        token_input = %s, token_output = %s, finished_at = %s
                    WHERE id = %s AND job_id = %s AND status = 'running'
                      AND worker_id = %s
                    """,
                    (
                        status.value,
                        output_json,
                        token_input,
                        token_output,
                        now,
                        claim.run_id,
                        claim.job.id,
                        claim.lease_owner,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("running agent run could not be finalized")

                await cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = %s, result_payload = %s::jsonb,
                        finished_at = CASE WHEN %s = 'completed' THEN %s ELSE NULL END,
                        updated_at = %s, lease_owner = NULL, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running' AND lease_owner = %s
                    """,
                    (
                        status.value,
                        output_json,
                        status.value,
                        now,
                        now,
                        claim.job.id,
                        claim.lease_owner,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("running analysis job could not be finalized")

                for sequence_no, trace in enumerate(traces, start=1):
                    await cursor.execute(
                        """
                        INSERT INTO tool_calls (
                            id, run_id, sequence_no, node_name, tool_name, status,
                            request_payload, response_payload, error_type,
                            duration_ms, token_input, token_output,
                            started_at, finished_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                            %s, %s, %s, %s, %s, %s
                        )
                        """,
                        _tool_call_values(claim.run_id, sequence_no, trace, now),
                    )

                for rank, item in enumerate(evidence, start=1):
                    await cursor.execute(
                        """
                        INSERT INTO retrieved_evidence (
                            id, run_id, evidence_id, event_id, rank,
                            retrieval_backend, score, text, source_url,
                            accepted, rejection_reason
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NULL)
                        """,
                        (
                            uuid4(),
                            claim.run_id,
                            str(item.get("evidence_id", f"rank-{rank}")),
                            str(item.get("event_id", "unknown")),
                            rank,
                            retrieval_backend,
                            float(item.get("score", 0.0) or 0.0),
                            str(item.get("text", "")),
                            item.get("source_url"),
                        ),
                    )
                await _insert_checkpoint(
                    cursor,
                    claim.run_id,
                    len(traces) + 1,
                    "completed",
                    "__end__",
                    result,
                )
            await connection.commit()

    async def record_execution_failure(
        self,
        claim: ClaimedRun,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        max_attempts: int,
    ) -> JobStatus:
        target = (
            JobStatus.RETRYING
            if retryable and claim.job.attempt_count < max_attempts
            else JobStatus.FAILED_CLOSED
        )
        now = datetime.now(timezone.utc)
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s,
                        output_state = %s::jsonb,
                        finished_at = %s
                    WHERE id = %s AND job_id = %s AND status = 'running'
                      AND worker_id = %s
                    """,
                    (
                        target.value,
                        json.dumps({"error_code": error_code, "message": message}),
                        now,
                        claim.run_id,
                        claim.job.id,
                        claim.lease_owner,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("failed agent run could not be finalized")
                await cursor.execute(
                    """
                    UPDATE analysis_jobs
                    SET status = %s, error_code = %s, error_message = %s,
                        finished_at = CASE WHEN %s = 'failed_closed' THEN %s ELSE NULL END,
                        updated_at = %s, lease_owner = NULL, lease_expires_at = NULL
                    WHERE id = %s AND status = 'running' AND lease_owner = %s
                    """,
                    (
                        target.value,
                        error_code,
                        message,
                        target.value,
                        now,
                        now,
                        claim.job.id,
                        claim.lease_owner,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("failed analysis job could not be finalized")
                await _insert_checkpoint(
                    cursor,
                    claim.run_id,
                    1,
                    "failure",
                    "__error__",
                    {"error_code": error_code, "message": message},
                )
            await connection.commit()
        return target

    async def recover_stale_jobs(self, max_attempts: int) -> dict[UUID, JobStatus]:
        """Move expired running attempts to replayable retry or failed-closed."""

        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        now = datetime.now(timezone.utc)
        connection = await self._connect()
        recovered: dict[UUID, JobStatus] = {}
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT id, attempt_count
                    FROM analysis_jobs
                    WHERE status = 'running' AND lease_expires_at < %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    (now,),
                )
                rows = await cursor.fetchall()
                for row in rows:
                    target = (
                        JobStatus.RETRYING
                        if int(row["attempt_count"]) < max_attempts
                        else JobStatus.FAILED_CLOSED
                    )
                    await cursor.execute(
                        """
                        UPDATE analysis_jobs
                        SET status = %s, error_code = 'worker_lease_expired',
                            error_message = 'Worker heartbeat lease expired',
                            recovery_count = recovery_count + 1,
                            lease_owner = NULL, lease_expires_at = NULL,
                            finished_at = CASE WHEN %s = 'failed_closed' THEN %s ELSE NULL END,
                            updated_at = %s
                        WHERE id = %s AND status = 'running'
                        """,
                        (target.value, target.value, now, now, row["id"]),
                    )
                    await cursor.execute(
                        """
                        UPDATE agent_runs
                        SET status = %s, recovery_reason = 'worker_lease_expired',
                            finished_at = %s
                        WHERE job_id = %s AND status = 'running'
                        """,
                        (target.value, now, row["id"]),
                    )
                    recovered[row["id"]] = target
            await connection.commit()
        return recovered


def _graph_input(job: JobRecord) -> dict[str, Any]:
    payload = job.request_payload
    return {
        "request_id": str(job.id),
        "event_id": job.event_id,
        "query": job.query,
        "comments": payload.get("comments", []),
        "tool_traces": [],
        "errors": [],
    }


async def _insert_checkpoint(
    cursor,
    run_id: UUID,
    sequence_no: int,
    kind: str,
    node_name: str,
    state: dict[str, Any],
) -> None:
    state_json = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    state_hash = hashlib.sha256(state_json.encode("utf-8")).hexdigest()
    await cursor.execute(
        """
        INSERT INTO run_checkpoints (
            id, run_id, sequence_no, checkpoint_kind,
            node_name, state, state_sha256
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        (uuid4(), run_id, sequence_no, kind, node_name, state_json, state_hash),
    )


def _state_sha256(state: dict[str, Any]) -> str:
    payload = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _token_totals(traces: list[dict[str, Any]]) -> tuple[int, int]:
    input_tokens = 0
    output_tokens = 0
    for trace in traces:
        usage = (trace.get("details") or {}).get("usage") or {}
        input_tokens += int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens += int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
    return input_tokens, output_tokens


def _retrieval_backend(traces: list[dict[str, Any]]) -> str:
    for trace in traces:
        if trace.get("node") == "evidence_retriever":
            return str((trace.get("details") or {}).get("backend", "unknown"))
    return "unknown"


def _tool_call_values(
    run_id: UUID,
    sequence_no: int,
    trace: dict[str, Any],
    finished_at: datetime,
) -> tuple[Any, ...]:
    trace_status = str(trace.get("status", "error"))
    persisted_status = {
        "ok": "succeeded",
        "degraded": "degraded",
        "error": "failed_closed",
    }.get(trace_status, "failed_closed")
    details = trace.get("details") or {}
    usage = details.get("usage") or {}
    duration_ms = max(0.0, float(trace.get("duration_ms", 0.0) or 0.0))
    return (
        uuid4(),
        run_id,
        sequence_no,
        str(trace.get("node", "unknown")),
        str(trace.get("node", "unknown")),
        persisted_status,
        json.dumps({}, ensure_ascii=False),
        json.dumps(
            {"trace_status": trace_status, "details": details},
            ensure_ascii=False,
            default=str,
        ),
        details.get("error_type") if trace_status == "error" else None,
        duration_ms,
        int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
        int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
        finished_at,
        finished_at,
    )
