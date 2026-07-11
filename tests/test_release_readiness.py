from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.release_readiness import (  # noqa: E402
    evaluate_release_readiness,
)


def test_public_repository_passes_release_blocking_checks() -> None:
    report = evaluate_release_readiness(PROJECT_ROOT)
    checks = {check["name"]: check for check in report["checks"]}

    assert report["passed"] is True
    assert report["failed_checks"] == []
    assert checks["required_public_files"]["passed"] is True
    assert checks["private_data_ignore_rules"]["passed"] is True
    assert checks["docker_context_ignore_rules"]["passed"] is True
    assert checks["synthetic_demo_boundary"]["passed"] is True
    assert checks["machine_readable_agent_evidence"]["passed"] is True
    assert checks["credential_pattern_scan"]["passed"] is True
