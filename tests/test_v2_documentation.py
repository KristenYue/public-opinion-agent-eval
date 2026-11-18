from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_readme_routes_to_current_v2_documents() -> None:
    readme = _read("README.md")

    assert "docs/ARCHITECTURE.md" in readme
    assert "docs/V2_API.md" in readme
    assert "docs/V2_ENGINEERING_LOG.md" in readme
    assert "docs/README.md" in readme


def test_readme_is_application_first_and_keeps_reproducible_evidence() -> None:
    readme = _read("README.md")

    assert readme.startswith("# NLP & RAG Agent — 文本智能分析与知识研判系统")
    expected_sections = (
        "## Project Overview",
        "## Application Scenarios",
        "## Features & Real Demonstration",
        "## System Architecture",
        "## Core Implementation",
        "## Engineering Results",
        "## Industry Applications",
        "## Quick Start",
        "## Evidence & Source Code",
        "## Validation & Limitations",
    )
    positions = [readme.index(section) for section in expected_sections]
    assert positions == sorted(positions)
    assert "38899760131" in readme
    assert "不是生产 SLA" in readme


def test_readme_separates_application_and_deployment_boundaries() -> None:
    readme = _read("README.md")

    assert "agent-runtime-quality-platform" in readme
    assert "docker compose up --build" in readme
    assert "不代表生产容量" in readme
    assert "真实平台部署" in readme


def test_document_index_separates_current_and_historical_material() -> None:
    index = _read("docs/README.md")
    week1 = _read("docs/V2_WEEK1_BASELINE.md")

    assert "## 当前权威说明" in index
    assert "## 历史检查点" in index
    assert "可执行代码与测试 → 当前权威说明 → 专项证据 → 历史检查点" in index
    assert "历史实现检查点" in week1


def test_current_api_document_covers_public_v2_contract() -> None:
    api = _read("docs/V2_API.md")

    for contract in (
        "/v2/jobs",
        "/v2/jobs/{job_id}",
        "/v2/jobs/{job_id}/trace",
        "Idempotency-Replayed",
        "manual_required",
        "failed_closed",
        "queue_unavailable",
        "X-Request-ID",
    ):
        assert contract in api
    assert "X-API-Key" in api
    assert "Project 级 RBAC" in api


def test_architecture_preserves_recovery_and_shadow_boundaries() -> None:
    architecture = _read("docs/ARCHITECTURE.md")

    assert "stateDiagram-v2" in architecture
    assert "input checkpoint" in architecture
    assert "不是 LangGraph 任意节点续跑" in architecture
    assert "Shadow 默认关闭" in architecture
    assert "不会修改正式 Job" in architecture
    assert "合成契约校准" in architecture


def test_readme_uses_verified_metric_language() -> None:
    readme = _read("README.md")

    for evidence in (
        "31.27%",
        "56.05%",
        "66.67%",
        "78.76%",
        "21.24%",
        "73.75%",
        "60 对版本化 case",
    ):
        assert evidence in readme
    assert "不是模型独立准确率" in readme
    assert "不是生产 SLA" in readme


def test_week2_document_is_explicitly_historical() -> None:
    historical = _read("docs/V2_WEEK2_JOB_API.md")

    assert "历史实现检查点" in historical
    assert "V2_API.md" in historical


def test_compose_delivery_evidence_is_current_without_claiming_local_docker() -> None:
    architecture = _read("docs/ARCHITECTURE.md")
    deployment = _read("docs/V2_DEPLOYMENT.md")
    roadmap = _read("docs/V2_ROADMAP_ALIGNMENT_2026-10-15.md")
    completion = _read("docs/PROJECT_COMPLETION_PLAN.md")

    for document in (architecture, deployment, roadmap, completion):
        assert "38899760131" in document
    assert "本机仍没有 Docker" in architecture
    assert "本机 Compose 已跑通" in deployment
    assert "3. [x] 增加 Docker 镜像构建与完整 Compose smoke test" in roadmap
    assert "容器与部署验收 | 已完成（CI）" in completion
