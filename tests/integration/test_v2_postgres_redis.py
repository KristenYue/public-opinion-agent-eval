import asyncio
import os
from uuid import UUID, uuid4

import pytest

from opinion_agent.v2.contracts import JobStatus
from opinion_agent.v2.dispatcher import ArqJobDispatcher
from opinion_agent.v2.jobs import JobSubmission
from opinion_agent.v2.repository import PsycopgJobRepository
from opinion_agent.v2.shadow import ShadowRecord
from opinion_agent.v2.shadow import RuntimeAdapterShadowRunner
from opinion_agent.v2.shadow_repository import PsycopgShadowSink
from opinion_agent.v2.worker import build_version_snapshot


pytestmark = pytest.mark.integration
PROJECT_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_pinned_runtime_adapter_matches_shadow_runner_contract(tmp_path) -> None:
    adapters = pytest.importorskip("agent_runtime_platform.adapters")

    class Graph:
        def invoke(self, state):
            return {
                **state,
                "analysis_report": {"review_status": "not_required"},
                "tool_traces": [],
                "errors": [],
            }

    adapter = adapters.OpinionAgentRuntimeAdapter(
        graph_provider=Graph,
        checkpoint_path=tmp_path / "runtime-shadow.sqlite3",
    )
    runner = RuntimeAdapterShadowRunner(adapter)
    result = asyncio.run(
        runner.invoke(
            {
                "request_id": "integration-request",
                "event_id": "integration-event",
                "query": "验证 Runtime shadow adapter",
                "comments": [{"sample_id": "c-1", "text": "集成测试评论"}],
            }
        )
    )

    assert result["event_id"] == "integration-event"
    assert result["analysis_report"]["review_status"] == "not_required"


def test_real_postgres_and_redis_job_lifecycle() -> None:
    asyncio.run(_exercise_lifecycle())


async def _exercise_lifecycle() -> None:
    repository = PsycopgJobRepository(os.environ["DATABASE_URL"])
    dispatcher = ArqJobDispatcher(
        os.environ["REDIS_URL"], queue_name="opinion-agent-integration"
    )
    unique = uuid4().hex
    submission = JobSubmission.model_validate(
        {
            "project_id": str(PROJECT_ID),
            "requested_by": "ci@example.invalid",
            "event_id": f"integration-{unique}",
            "query": "验证可审计异步任务链路",
            "comments": [{"sample_id": "c-1", "text": "集成测试评论"}],
        }
    )

    try:
        assert await repository.ping() is True
        assert await dispatcher.ping() is True

        created = await repository.create_or_get(submission, f"integration-{unique}")
        replayed = await repository.create_or_get(submission, f"integration-{unique}")
        assert created.created is True
        assert replayed.created is False
        assert replayed.job.id == created.job.id

        await dispatcher.enqueue(created.job.id)
        claim = await repository.claim_for_execution(
            created.job.id,
            build_version_snapshot(),
            trace_id=uuid4().hex,
            worker_id="integration-worker",
            lease_seconds=30,
        )
        assert claim is not None
        assert await repository.heartbeat(claim, lease_seconds=30) is True

        result = {
            "analysis_report": {"review_status": "not_required"},
            "tool_traces": [],
            "retrieved_evidence": [],
        }
        await repository.finish_execution(claim, result, JobStatus.COMPLETED)
        await PsycopgShadowSink(os.environ["DATABASE_URL"]).record_shadow(
            ShadowRecord(
                job_id=created.job.id,
                official_run_id=claim.run_id,
                trace_id=claim.trace_id,
                candidate_name="integration-shadow",
                status="succeeded",
                duration_ms=1.5,
                result_payload={"analysis_report": {"source": "shadow"}},
            )
        )
        persisted = await repository.get(created.job.id)
        assert persisted is not None
        assert persisted.status == JobStatus.COMPLETED
        assert persisted.attempt_count == 1
        assert persisted.result_payload == result

        trace = await repository.get_trace(created.job.id)
        assert trace is not None
        assert trace.job.id == created.job.id
        assert len(trace.runs) == 1
        assert trace.runs[0].id == claim.run_id
        assert [item.checkpoint_kind for item in trace.runs[0].checkpoints] == [
            "input_replay",
            "completed",
        ]
        assert trace.runs[0].tool_calls == []

        connection = await repository._connect()
        async with connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT status, result_payload
                    FROM shadow_runs
                    WHERE official_run_id = %s AND candidate_name = %s
                    """,
                    (claim.run_id, "integration-shadow"),
                )
                shadow_row = await cursor.fetchone()
        assert shadow_row["status"] == "succeeded"
        assert shadow_row["result_payload"]["analysis_report"]["source"] == "shadow"
        trace_with_shadow = await repository.get_trace(created.job.id)
        assert trace_with_shadow is not None
        assert len(trace_with_shadow.shadow_runs) == 1
        assert trace_with_shadow.shadow_runs[0].candidate_name == "integration-shadow"
    finally:
        await dispatcher.close()
