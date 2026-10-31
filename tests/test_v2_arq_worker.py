from importlib import import_module
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _run_immediate(coroutine):
    try:
        yielded = coroutine.send(None)
    except StopIteration as stop:
        return stop.value
    coroutine.close()
    raise AssertionError(f"fake coroutine unexpectedly suspended with {yielded!r}")


def test_arq_worker_settings_import_with_explicit_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ARQ_QUEUE_NAME", "worker-test")
    monkeypatch.delenv("RUNTIME_SHADOW_ENABLED", raising=False)
    sys.modules.pop("opinion_agent.v2.arq_worker", None)

    module = import_module("opinion_agent.v2.arq_worker")

    assert module.WorkerSettings.functions == [module.run_analysis_job]
    assert module.WorkerSettings.queue_name == "worker-test"
    assert module.WorkerSettings.redis_settings.host == "localhost"


def test_worker_environment_error_is_actionable(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_WORKER_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("RUNTIME_SHADOW_ENABLED", raising=False)
    sys.modules.pop("opinion_agent.v2.arq_worker", None)
    module = import_module("opinion_agent.v2.arq_worker")

    with pytest.raises(RuntimeError, match="MISSING_WORKER_ENV is required"):
        module._required_env("MISSING_WORKER_ENV")


def test_runtime_shadow_is_strictly_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("RUNTIME_SHADOW_ENABLED", raising=False)
    sys.modules.pop("opinion_agent.v2.arq_worker", None)
    module = import_module("opinion_agent.v2.arq_worker")

    def must_not_load():
        raise AssertionError("optional Runtime package must not load while disabled")

    monkeypatch.setattr(module, "_load_runtime_adapter", must_not_load)

    assert module._build_shadow_executor("postgresql://example/db") is None


def test_runtime_shadow_rejects_ambiguous_flag(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RUNTIME_SHADOW_ENABLED", "sometimes")
    sys.modules.pop("opinion_agent.v2.arq_worker", None)
    module = import_module("opinion_agent.v2.arq_worker")

    with pytest.raises(RuntimeError, match="RUNTIME_SHADOW_ENABLED must be one of"):
        module._build_shadow_executor("postgresql://example/db")


def test_runtime_shadow_enabled_builds_isolated_executor(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RUNTIME_SHADOW_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_SHADOW_CANDIDATE", "candidate-under-test")
    monkeypatch.setenv("RUNTIME_SHADOW_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("RUNTIME_SHADOW_CHECKPOINT_PATH", "shadow-test.sqlite3")
    sys.modules.pop("opinion_agent.v2.arq_worker", None)
    module = import_module("opinion_agent.v2.arq_worker")

    class FakeAdapter:
        def __init__(self, **kwargs):
            self.options = kwargs

    monkeypatch.setattr(module, "_load_runtime_adapter", lambda: FakeAdapter)
    shadow = module._build_shadow_executor("postgresql://example/db")

    assert shadow is not None
    assert shadow.candidate_name == "candidate-under-test"
    assert shadow.timeout_seconds == 7
    assert shadow.runner.adapter.options["checkpoint_path"] == "shadow-test.sqlite3"
    assert shadow.sink.dsn == "postgresql://example/db"
