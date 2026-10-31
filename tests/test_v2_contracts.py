from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.v2 import (  # noqa: E402
    JobStatus,
    RunVersionSnapshot,
    VersionedComponent,
    assert_job_transition,
    can_transition_job,
)


def _component(name: str, version: str) -> VersionedComponent:
    return VersionedComponent(name=name, version=version, config={"temperature": 0})


def test_job_state_machine_covers_retry_degrade_review_and_completion() -> None:
    assert can_transition_job("queued", "running")
    assert can_transition_job(JobStatus.RUNNING, JobStatus.RETRYING)
    assert can_transition_job("retrying", "degraded")
    assert can_transition_job("degraded", "manual_required")
    assert can_transition_job("manual_required", "completed")


@pytest.mark.parametrize("terminal", ["completed", "failed_closed"])
def test_terminal_job_status_cannot_be_reopened(terminal: str) -> None:
    assert not can_transition_job(terminal, "running")
    with pytest.raises(ValueError, match="invalid analysis job transition"):
        assert_job_transition(terminal, "running")


def test_version_snapshot_is_stable_and_sensitive_to_prompt_version() -> None:
    baseline = RunVersionSnapshot(
        model=_component("qwen", "2026-09"),
        prompt=_component("event-review", "v1"),
        toolset=_component("opinion-tools", "v2"),
        policy=_component("review-gate", "v1.5"),
    )
    same = RunVersionSnapshot.model_validate(baseline.model_dump())
    candidate = baseline.model_copy(
        update={"prompt": _component("event-review", "v2")}
    )

    assert baseline.fingerprint() == same.fingerprint()
    assert baseline.fingerprint() != candidate.fingerprint()
    assert len(baseline.model.resolved_hash()) == 64


def test_version_component_rejects_ambiguous_identity() -> None:
    with pytest.raises(ValueError, match="surrounding whitespace"):
        VersionedComponent(name=" qwen", version="v1")


def test_postgres_migration_contains_all_required_audit_tables() -> None:
    migration = (
        PROJECT_ROOT
        / "src"
        / "opinion_agent"
        / "v2"
        / "migrations"
        / "0001_auditable_jobs.sql"
    ).read_text(encoding="utf-8")

    required_tables = {
        "projects",
        "analysis_jobs",
        "comments",
        "retrieved_evidence",
        "agent_runs",
        "tool_calls",
        "human_reviews",
        "model_versions",
    }
    for table in required_tables:
        assert f"CREATE TABLE {table}" in migration
    assert "UNIQUE (project_id, idempotency_key)" in migration
    assert "version_snapshot JSONB NOT NULL" in migration


def test_recovery_migration_distinguishes_replay_from_node_resume() -> None:
    migration = (
        PROJECT_ROOT
        / "src"
        / "opinion_agent"
        / "v2"
        / "migrations"
        / "0002_leases_and_checkpoints.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE run_checkpoints" in migration
    assert "lease_expires_at" in migration
    assert "input_replay" in migration
    assert "not LangGraph node-level resume checkpoints" in migration


def test_project_member_migration_has_explicit_rbac_roles() -> None:
    migration = (
        PROJECT_ROOT
        / "src"
        / "opinion_agent"
        / "v2"
        / "migrations"
        / "0004_project_members.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE project_members" in migration
    assert "'owner', 'analyst', 'viewer'" in migration
    assert "PRIMARY KEY (project_id, subject)" in migration
