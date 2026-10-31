import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from opinion_agent.v2.shadow import RuntimeAdapterShadowRunner, ShadowRecord
from opinion_agent.v2.shadow_repository import PsycopgShadowSink


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeCursor:
    def __init__(self) -> None:
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement, parameters):
        self.statements.append((statement, parameters))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_instance

    async def commit(self):
        self.commits += 1


def test_shadow_migration_owns_an_independent_append_only_table() -> None:
    migration = (
        PROJECT_ROOT / "src/opinion_agent/v2/migrations/0003_shadow_runs.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE shadow_runs" in migration
    assert "official_run_id UUID NOT NULL REFERENCES agent_runs(id)" in migration
    assert "UNIQUE (official_run_id, candidate_name)" in migration
    assert "ALTER TABLE analysis_jobs" not in migration
    assert "ALTER TABLE agent_runs" not in migration


def test_postgres_shadow_sink_writes_only_shadow_runs(monkeypatch) -> None:
    connection = FakeConnection()
    sink = PsycopgShadowSink("postgresql://example.invalid/database")

    async def connect():
        return connection

    monkeypatch.setattr(sink, "_connect", connect)
    record = ShadowRecord(
        job_id=uuid4(),
        official_run_id=uuid4(),
        trace_id="trace-1",
        candidate_name="runtime-v1",
        status="succeeded",
        duration_ms=12.5,
        result_payload={"analysis_report": {"source": "shadow"}},
    )

    asyncio.run(sink.record_shadow(record))

    statement, parameters = connection.cursor_instance.statements[0]
    assert "INSERT INTO shadow_runs" in statement
    assert "analysis_jobs" not in statement
    assert "agent_runs" not in statement
    assert "ON CONFLICT (official_run_id, candidate_name) DO NOTHING" in statement
    assert json.loads(parameters[7]) == record.result_payload
    assert connection.commits == 1


def test_runtime_adapter_runner_maps_state_and_returns_candidate_result() -> None:
    class Adapter:
        def __init__(self) -> None:
            self.calls = []

        async def analyze(self, request, *, task_id=None):
            self.calls.append((request, task_id))
            return SimpleNamespace(
                status=SimpleNamespace(value="completed"),
                result={"analysis_report": {"source": "runtime"}},
            )

    adapter = Adapter()
    runner = RuntimeAdapterShadowRunner(adapter)
    state = {
        "request_id": "request-1",
        "event_id": "event-1",
        "query": "分析事件",
        "comments": [{"sample_id": "c-1", "text": "评论"}],
        "official_only": "must not cross the adapter boundary",
    }

    result = asyncio.run(runner.invoke(state))

    assert result["analysis_report"]["source"] == "runtime"
    assert adapter.calls == [
        (
            {
                "event_id": "event-1",
                "query": "分析事件",
                "comments": [{"sample_id": "c-1", "text": "评论"}],
            },
            "request-1:shadow",
        )
    ]


def test_runtime_adapter_runner_rejects_noncompleted_runtime_result() -> None:
    class Adapter:
        async def analyze(self, request, *, task_id=None):
            return SimpleNamespace(status="failed_closed", result=None)

    with pytest.raises(RuntimeError, match="failed_closed"):
        asyncio.run(
            RuntimeAdapterShadowRunner(Adapter()).invoke(
                {
                    "request_id": "request-1",
                    "event_id": "event-1",
                    "query": "分析事件",
                    "comments": [{"sample_id": "c-1", "text": "评论"}],
                }
            )
        )
