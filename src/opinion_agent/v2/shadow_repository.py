"""PostgreSQL persistence for isolated shadow execution records."""

from __future__ import annotations

import json
from uuid import uuid4

from .repository import _load_psycopg
from .shadow import ShadowRecord


class PsycopgShadowSink:
    """Append the first candidate record for one official run."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("database DSN must not be blank")
        self.dsn = dsn

    async def _connect(self):
        psycopg, dict_row = _load_psycopg()
        return await psycopg.AsyncConnection.connect(self.dsn, row_factory=dict_row)

    async def record_shadow(self, record: ShadowRecord) -> None:
        result_json = (
            json.dumps(record.result_payload, ensure_ascii=False)
            if record.result_payload is not None
            else None
        )
        connection = await self._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO shadow_runs (
                        id, job_id, official_run_id, trace_id, candidate_name,
                        status, duration_ms, result_payload, error_type,
                        error_message
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
                    )
                    ON CONFLICT (official_run_id, candidate_name) DO NOTHING
                    """,
                    (
                        uuid4(),
                        record.job_id,
                        record.official_run_id,
                        record.trace_id,
                        record.candidate_name,
                        record.status,
                        record.duration_ms,
                        result_json,
                        record.error_type,
                        record.error_message,
                    ),
                )
            await connection.commit()
