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


def test_readme_homepage_has_exactly_five_reproducible_evidence_rows() -> None:
    readme = _read("README.md")
    section = readme.split("## 5 项可复现核心证据", 1)[1].split("### 这些数字应该怎样理解", 1)[0]

    evidence_rows = [line for line in section.splitlines() if line.startswith("| ")]
    assert len(evidence_rows) == 6  # header + exactly five evidence rows
    assert "38899760131" in section
    assert "不代表生产 SLA" in section


def test_readme_separates_project_and_deployment_boundaries() -> None:
    readme = _read("README.md")

    assert "agent-runtime-quality-platform" in readme
    assert "旧的 [agent-reliability-eval]" in readme
    assert "V1 面试 Demo 使用根目录 `Dockerfile`" in readme
    assert "V2 生产形态使用 `Dockerfile.v2` 与 `compose.yaml`" in readme
    assert "`v1.0-frozen-2026-09-11` 只冻结 V1 基线" in readme


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


def test_three_minute_script_uses_verified_metric_language() -> None:
    script = _read("docs/INTERVIEW_DEMO_SCRIPT.md")

    for evidence in (
        "31.27%",
        "56.05%",
        "66.67%",
        "78.76%",
        "21.24%",
        "73.75%",
        "60 对 Runtime case",
    ):
        assert evidence in script
    assert "不会称它为模型准确率" in script
    assert "不是生产 SLA" in script
    assert "不要伪造实时任务" in script


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
