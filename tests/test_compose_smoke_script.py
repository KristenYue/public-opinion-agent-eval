from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts/smoke_v2_compose.py"


def _load_smoke_module():
    spec = spec_from_file_location("compose_smoke_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wait_until_retries_connection_reset_during_service_startup(monkeypatch) -> None:
    smoke = _load_smoke_module()
    attempts = 0

    def check():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("service is still starting")
        return {"database": "ok"}

    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)

    assert smoke.wait_until("service", check, time.monotonic() + 1) == {
        "database": "ok"
    }
    assert attempts == 2


def test_wait_until_does_not_hide_contract_errors(monkeypatch) -> None:
    smoke = _load_smoke_module()
    monkeypatch.setattr(smoke.time, "sleep", lambda _seconds: None)

    def check():
        raise KeyError("contract field is absent")

    try:
        smoke.wait_until("service", check, time.monotonic() + 1)
    except KeyError as exc:
        assert exc.args == ("contract field is absent",)
    else:
        raise AssertionError("contract errors must fail immediately")
