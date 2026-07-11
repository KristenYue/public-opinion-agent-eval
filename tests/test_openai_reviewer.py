from pathlib import Path
import json
import sys

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.reviewer import OpenAICompatibleReviewer  # noqa: E402
from opinion_agent.agent.reviewer import ReviewItemModel  # noqa: E402


def review_state() -> dict[str, object]:
    return {
        "request_id": "request-1",
        "event_id": "event-1",
        "query": "review",
        "comments": [
            {
                "sample_id": "a",
                "text": "不好",
                "context": "原帖上下文",
                "source_url": "https://example.com/post",
            }
        ],
        "sentiment_results": [
            {
                "sample_id": "a",
                "text": "不好",
                "label": "Negative",
                "confidence": 0.7,
                "probabilities": {"Negative": 0.7},
                "source": "legacy_xgboost",
                "secondary_label": "Neutral",
                "secondary_score": 0.5,
                "models_agree": False,
            }
        ],
        "retrieved_evidence": [],
        "tool_traces": [],
        "errors": [],
    }


def success_response(sample_id: str = "a") -> httpx.Response:
    content = json.dumps(
        {
            "items": [
                {
                    "sample_id": sample_id,
                    "label": "Negative",
                    "rationale": "评论表达明确否定。",
                    "confidence": "High",
                }
            ],
            "summary": "复核完成",
        },
        ensure_ascii=False,
    )
    return httpx.Response(
        200,
        request=httpx.Request("POST", "https://example.com/chat/completions"),
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
    )


def test_reviewer_retries_429_and_reports_usage() -> None:
    calls: list[dict[str, object]] = []
    delays: list[float] = []

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if len(calls) == 1:
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                headers={"Retry-After": "0.01"},
            )
        return success_response()

    reviewer = OpenAICompatibleReviewer(
        "https://example.com/v1",
        "secret",
        "model",
        max_attempts=2,
        backoff_seconds=0.01,
        post_func=post,
        sleep_func=delays.append,
    )

    result = reviewer.review(review_state())  # type: ignore[arg-type]

    assert result["attempts"] == 2
    assert result["usage"]["total_tokens"] == 120
    assert result["usage"]["input_chars"] > 0
    assert len(calls) == 2
    assert delays == [0.01]
    assert calls[0]["headers"]["Idempotency-Key"] == calls[1]["headers"]["Idempotency-Key"]


def test_reviewer_rejects_missing_and_unexpected_item_ids() -> None:
    reviewer = OpenAICompatibleReviewer(
        "https://example.com/v1",
        "secret",
        "model",
        post_func=lambda *args, **kwargs: success_response("wrong-id"),
    )

    with pytest.raises(ValueError, match="item contract violated"):
        reviewer.review(review_state())  # type: ignore[arg-type]


def test_reviewer_rejects_input_over_budget() -> None:
    reviewer = OpenAICompatibleReviewer(
        "https://example.com/v1",
        "secret",
        "model",
        max_input_chars=10,
        post_func=lambda *args, **kwargs: success_response(),
    )

    with pytest.raises(ValueError, match="input budget exceeded"):
        reviewer.review(review_state())  # type: ignore[arg-type]
def test_review_item_normalizes_provider_confidence_and_long_rationale() -> None:
    item = ReviewItemModel.model_validate(
        {
            "sample_id": "sample",
            "label": "Neutral",
            "rationale": "x" * 350,
            "confidence": 0.85,
        }
    )

    assert item.confidence == "High"
    assert len(item.rationale) == 300
