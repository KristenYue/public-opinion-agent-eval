from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_compose_declares_complete_v2_runtime() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    for service in (
        "postgres",
        "redis",
        "migrate",
        "bootstrap",
        "api",
        "worker",
        "prometheus",
        "grafana",
    ):
        assert f"  {service}:" in compose
    assert "service_healthy" in compose
    assert "service_completed_successfully" in compose
    assert "scripts/apply_v2_migrations.py" in compose
    assert "scripts/bootstrap_v2_project.py" in compose
    assert "opinion_agent.v2.arq_worker.WorkerSettings" in compose
    assert "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}" in compose
    assert "${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD}" in compose


def test_v2_image_uses_readiness_and_does_not_download_model_at_build_time() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile.v2").read_text(encoding="utf-8")

    assert '".[production,shadow]"' in dockerfile
    assert "opinion_agent.api:app" in dockerfile
    assert "/ready" in dockerfile
    assert "SentenceTransformer(" not in dockerfile


def test_shadow_deployment_is_pinned_and_default_off() -> None:
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    environment = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "0cd15fac75354adf3161cac473614cc7f52f66d1" in pyproject
    assert "RUNTIME_SHADOW_ENABLED: ${RUNTIME_SHADOW_ENABLED:-false}" in compose
    assert "RUNTIME_SHADOW_ENABLED=false" in environment


def test_integration_ci_collects_only_integration_tests() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    assert "pytest -q tests/integration -m integration" in workflow
    assert "run: python -m pytest -q -m integration" not in workflow
    assert 'pip install -e ".[demo,training,production,shadow,dev]"' in workflow
    assert "run: python scripts/evaluate_runtime_gate.py" in workflow


def test_ci_builds_and_smoke_tests_the_complete_compose_stack() -> None:
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    smoke = (PROJECT_ROOT / "scripts/smoke_v2_compose.py").read_text(
        encoding="utf-8"
    )

    assert "  compose-smoke:" in workflow
    assert "docker compose config --quiet" in workflow
    assert "docker compose up --detach --build" in workflow
    assert "python scripts/smoke_v2_compose.py" in workflow
    assert "if: always()" in workflow
    assert "docker compose down --volumes --remove-orphans" in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 3
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert workflow.count("actions/checkout@v5") == 3
    assert workflow.count("actions/setup-python@v6") == 3
    assert 'dependencies.get("database") is True' in smoke
    assert 'dependencies.get("queue") is True' in smoke
    assert 'dependencies.get("postgres")' not in smoke
    assert 'dependencies.get("redis")' not in smoke
    assert 'headers.get("idempotency-replayed"' in smoke
    assert 'headers.get("Idempotency-Replayed"' not in smoke

    for contract in (
        "/ready",
        "/v2/jobs",
        "/trace",
        "/metrics",
        "idempotency-replayed",
        "input_replay",
        "shadow_runs",
        "opinion_agent_http_requests_total",
        "Prometheus readiness",
        "Grafana health",
        "ConnectionError",
    ):
        assert contract in smoke


def test_observability_assets_are_parseable_and_use_bounded_route_labels() -> None:
    import json

    dashboard = json.loads(
        (PROJECT_ROOT / "deploy/grafana/dashboards/opinion-agent-api.json").read_text(
            encoding="utf-8"
        )
    )
    prometheus = (PROJECT_ROOT / "deploy/prometheus.yml").read_text(encoding="utf-8")
    source = (PROJECT_ROOT / "src/opinion_agent/api.py").read_text(encoding="utf-8")

    assert dashboard["uid"] == "opinion-agent-api"
    assert 'targets: ["api:8000"]' in prometheus
    assert 'getattr(route_object, "path", "unmatched")' in source
    assert "request.url.path" not in source
