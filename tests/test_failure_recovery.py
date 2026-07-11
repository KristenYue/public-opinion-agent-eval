from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.failure_recovery import (  # noqa: E402
    run_failure_recovery_benchmark,
)


def test_failure_recovery_benchmark_covers_retry_and_fallback_paths() -> None:
    report = run_failure_recovery_benchmark()
    scenarios = {item["name"]: item for item in report["scenario_results"]}

    assert report["scenarios"] == report["passed"] == 7
    assert report["scenario_success_rate"] == 1.0
    assert report["external_network_calls"] == 0
    assert scenarios["transient_timeout_then_success"]["actual_review_status"] == (
        "llm_completed"
    )
    assert scenarios["rate_limit_then_success"]["idempotency_key_stable"] is True
    assert scenarios["persistent_503"]["http_calls"] == 3
    assert scenarios["non_retryable_400"]["http_calls"] == 1
    assert scenarios["input_budget_exceeded"]["http_calls"] == 0
    assert all(item["agent_contract_passed"] for item in scenarios.values())
    assert all(
        item["manual_fallback_action"]
        for item in scenarios.values()
        if item["actual_review_status"] == "llm_failed"
    )
