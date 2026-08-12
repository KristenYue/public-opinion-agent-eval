from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation.performance import (  # noqa: E402
    extract_path_counts,
    extract_usage,
    percentile,
    summarize_runs,
)


def test_percentile_interpolates_and_validates_input() -> None:
    assert percentile([10, 20, 30], 0.5) == 20
    assert percentile([10, 20], 0.95) == 19.5


def test_extract_path_counts_maps_offline_review_to_manual() -> None:
    result = {
        "analysis_report": {"review_status": "manual_required"},
        "route_decision": {
            "items": [
                {"needs_review": False},
                {"needs_review": True},
            ]
        },
    }

    assert extract_path_counts(result) == {"fast_path": 1, "manual_required": 1}


def test_extract_usage_uses_provider_reported_values() -> None:
    result = {
        "review_result": {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "input_chars": 500,
            }
        }
    }

    assert extract_usage(result)["total_tokens"] == 120


def test_summarize_runs_reports_latency_paths_usage_and_failures() -> None:
    records = [
        {
            "wall_latency_ms": 10.0,
            "result": {
                "analysis_report": {"review_status": "llm_completed"},
                "sentiment_results": [
                    {"decision_path": "fast_path"},
                    {"decision_path": "qwen_reviewed"},
                ],
                "review_result": {"usage": {"total_tokens": 40}},
                "tool_traces": [
                    {"node": "classifier", "status": "ok", "duration_ms": 4.0}
                ],
                "errors": [],
            },
        },
        {
            "wall_latency_ms": 20.0,
            "result": {
                "analysis_report": {"review_status": "manual_required"},
                "route_decision": {"items": [{"needs_review": True}]},
                "tool_traces": [
                    {"node": "classifier", "status": "error", "duration_ms": 5.0}
                ],
                "errors": [{"error_type": "TimeoutError"}],
            },
        },
    ]

    summary = summarize_runs(records)

    assert summary["wall_latency_ms"]["p50"] == 15.0
    assert summary["path_counts"] == {
        "fast_path": 1,
        "qwen_reviewed": 1,
        "manual_required": 1,
    }
    assert summary["provider_reported_usage"]["total_tokens"] == 40
    assert summary["failed_run_count"] == 1
