"""Deterministic failure-injection benchmark for the external review boundary."""

from collections.abc import Callable
from typing import Any
import json

import httpx

from opinion_agent.agent.graph import build_opinion_graph
from opinion_agent.agent.reviewer import OpenAICompatibleReviewer
from opinion_agent.sentiment.classifier import Prediction
from opinion_agent.sentiment.snownlp_baseline import SecondaryPrediction

from .agent_contracts import evaluate_agent_contract


class _PrimaryClassifier:
    def predict(self, text: str) -> Prediction:
        return Prediction("Negative", 0.72, {"Negative": 0.72}, text)


class _DisagreeingSecondaryClassifier:
    def predict(self, text: str) -> SecondaryPrediction:
        return SecondaryPrediction("Neutral", 0.5)


class _EvidenceRetriever:
    def retrieve(self, query: str, top_k: int, exclude_event_id: str):
        return [
            {
                "evidence_id": "historical-1:card",
                "event_id": "historical-1",
                "chunk_type": "event_card",
                "text": "历史相似事件的公开处置摘要。",
                "source_url": "https://example.com/history/1",
                "score": 0.81,
            }
        ]


def _request() -> dict[str, Any]:
    return {
        "request_id": "failure-injection-request",
        "event_id": "current-event",
        "query": "识别争议评论并给出处置建议",
        "comments": [
            {
                "sample_id": "sample-1",
                "text": "这项调整让普通消费者承担了更多成本",
                "context": "政策调整后的公众讨论",
                "source_url": "https://example.com/current/1",
            }
        ],
        "tool_traces": [],
        "errors": [],
    }


def _success_response(sample_id: str = "sample-1") -> httpx.Response:
    content = json.dumps(
        {
            "items": [
                {
                    "sample_id": sample_id,
                    "label": "Negative",
                    "rationale": "评论明确表达对成本上升的担忧。",
                    "confidence": "High",
                }
            ],
            "summary": "复核完成，建议持续跟踪成本议题。",
        },
        ensure_ascii=False,
    )
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://review.example/v1/chat/completions"),
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        },
    )


def _status_response(status_code: int, retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://review.example/v1/chat/completions"),
        headers=headers,
    )


def _content_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://review.example/v1/chat/completions"),
        json={"choices": [{"message": {"content": content}}]},
    )


def _scenario_steps() -> list[dict[str, Any]]:
    timeout = httpx.ReadTimeout(
        "simulated timeout",
        request=httpx.Request("POST", "https://review.example/v1/chat/completions"),
    )
    wrong_id = json.dumps(
        {
            "items": [
                {
                    "sample_id": "invented-id",
                    "label": "Negative",
                    "rationale": "无效样本标识。",
                    "confidence": "High",
                }
            ],
            "summary": "错误示例",
        },
        ensure_ascii=False,
    )
    return [
        {
            "name": "transient_timeout_then_success",
            "steps": [timeout, _success_response()],
            "expected_status": "llm_completed",
            "expected_calls": 2,
        },
        {
            "name": "rate_limit_then_success",
            "steps": [_status_response(429, "0"), _success_response()],
            "expected_status": "llm_completed",
            "expected_calls": 2,
        },
        {
            "name": "persistent_503",
            "steps": [_status_response(503), _status_response(503), _status_response(503)],
            "expected_status": "llm_failed",
            "expected_calls": 3,
        },
        {
            "name": "non_retryable_400",
            "steps": [_status_response(400)],
            "expected_status": "llm_failed",
            "expected_calls": 1,
        },
        {
            "name": "malformed_json",
            "steps": [_content_response("not valid json")],
            "expected_status": "llm_failed",
            "expected_calls": 1,
        },
        {
            "name": "unexpected_item_id",
            "steps": [_content_response(wrong_id)],
            "expected_status": "llm_failed",
            "expected_calls": 1,
        },
        {
            "name": "input_budget_exceeded",
            "steps": [],
            "expected_status": "llm_failed",
            "expected_calls": 0,
            "max_input_chars": 10,
        },
    ]


def run_failure_recovery_benchmark() -> dict[str, Any]:
    """Run isolated reviewer failures through the complete graph without network access."""
    scenario_results: list[dict[str, Any]] = []
    max_attempts = 3

    for scenario in _scenario_steps():
        calls: list[dict[str, Any]] = []
        steps = list(scenario["steps"])

        def post(url: str, **kwargs: Any) -> httpx.Response:
            calls.append({"url": url, **kwargs})
            step = steps[len(calls) - 1]
            if isinstance(step, Exception):
                raise step
            return step

        reviewer = OpenAICompatibleReviewer(
            "https://review.example/v1",
            "benchmark-secret",
            "benchmark-reviewer",
            max_attempts=max_attempts,
            backoff_seconds=0,
            max_input_chars=int(scenario.get("max_input_chars", 50_000)),
            post_func=post,
            sleep_func=lambda _: None,
        )
        graph = build_opinion_graph(
            _PrimaryClassifier(),  # type: ignore[arg-type]
            _EvidenceRetriever(),  # type: ignore[arg-type]
            _DisagreeingSecondaryClassifier(),  # type: ignore[arg-type]
            reviewer,
        )
        request = _request()
        result = graph.invoke(request)
        contract = evaluate_agent_contract(request, result)
        report = result["analysis_report"]
        actual_status = report["review_status"]
        expected_status = scenario["expected_status"]
        expected_failure = expected_status == "llm_failed"
        errors = result.get("errors", [])
        idempotency_keys = [
            str(call.get("headers", {}).get("Idempotency-Key", "")) for call in calls
        ]
        idempotency_stable = bool(idempotency_keys) and len(set(idempotency_keys)) == 1
        if not calls:
            idempotency_stable = True
        manual_action_present = (
            "人工复核争议评论并记录最终依据" in report["recommended_actions"]
        )
        failure_visibility_ok = (
            bool(errors) and all(error.get("recoverable") is True for error in errors)
            if expected_failure
            else not errors
        )
        scenario_passed = all(
            [
                actual_status == expected_status,
                len(calls) == scenario["expected_calls"],
                len(calls) <= max_attempts,
                idempotency_stable,
                failure_visibility_ok,
                manual_action_present if expected_failure else True,
                contract["passed"],
            ]
        )
        scenario_results.append(
            {
                "name": scenario["name"],
                "passed": scenario_passed,
                "expected_review_status": expected_status,
                "actual_review_status": actual_status,
                "http_calls": len(calls),
                "expected_http_calls": scenario["expected_calls"],
                "bounded_retry": len(calls) <= max_attempts,
                "idempotency_key_stable": idempotency_stable,
                "failure_visible": bool(errors),
                "manual_fallback_action": manual_action_present,
                "agent_contract_passed": contract["passed"],
                "failed_contract_checks": contract["failed_checks"],
                "error_types": [str(error.get("error_type", "")) for error in errors],
                "trajectory": [trace["node"] for trace in result["tool_traces"]],
            }
        )

    passed = sum(int(scenario["passed"]) for scenario in scenario_results)
    return {
        "status": "offline_deterministic_failure_injection",
        "scenarios": len(scenario_results),
        "passed": passed,
        "scenario_success_rate": passed / len(scenario_results),
        "external_network_calls": 0,
        "scenario_results": scenario_results,
        "limitations": [
            "The benchmark injects deterministic HTTP and payload failures; it does not measure a live provider SLA.",
            "The classifier and retriever are controlled stubs so the benchmark isolates orchestration recovery behavior.",
        ],
    }
