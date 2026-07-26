from pathlib import Path
import json
import sys

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.reviewer import (  # noqa: E402
    OfflineDemoReviewer,
    OpenAICompatibleReviewer,
)
from opinion_agent.agent.reviewer import ReviewBatchModel, ReviewItemModel  # noqa: E402


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
    user_payload = json.loads(calls[0]["json"]["messages"][1]["content"])
    assert user_payload["prompt_version"] == "event_stance_v2"
    assert "事件本身是喜讯不等于评论为正面" in user_payload["label_rules"]["Neutral"]
    assert user_payload["comments"][0]["context"] == "原帖上下文"
    assert "model_disagreement" in user_payload["comments"][0]["review_reasons"]
    assert result["prompt_version"] == "event_stance_v2"


def test_strict_live_test_sends_confident_agreement_to_reviewer() -> None:
    calls: list[dict[str, object]] = []
    state = review_state()
    state["review_policy"] = "strict_live_test"
    state["sentiment_results"][0].update(
        {
            "text": "这是一条长度足够且两个模型方向一致的现场评论",
            "label": "Positive",
            "confidence": 0.99,
            "secondary_label": "Positive",
            "models_agree": True,
        }
    )

    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return success_response()

    reviewer = OpenAICompatibleReviewer(
        "https://example.com/v1",
        "secret",
        "model",
        post_func=post,
    )

    reviewer.review(state)  # type: ignore[arg-type]

    user_payload = json.loads(calls[0]["json"]["messages"][1]["content"])
    assert user_payload["comments"][0]["review_reasons"] == ["strict_live_test"]


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


def test_reviewer_reports_bounded_provider_error_for_401() -> None:
    def reject(url, **kwargs):
        return httpx.Response(
            401,
            request=httpx.Request("POST", url),
            json={"code": "InvalidApiKey", "message": "API key is invalid"},
        )

    reviewer = OpenAICompatibleReviewer(
        "https://example.com/v1",
        "secret-that-must-not-appear",
        "model",
        post_func=reject,
    )

    with pytest.raises(RuntimeError, match="InvalidApiKey") as error:
        reviewer.review(review_state())  # type: ignore[arg-type]

    assert "secret-that-must-not-appear" not in str(error.value)


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


def test_review_batch_truncates_verbose_provider_summary() -> None:
    batch = ReviewBatchModel.model_validate(
        {
            "items": [
                {
                    "sample_id": "sample",
                    "label": "Neutral",
                    "rationale": "事实陈述。",
                    "confidence": "High",
                }
            ],
            "summary": "x" * 700,
        }
    )

    assert len(batch.summary) == 500


def test_offline_demo_reviewer_replays_known_and_abstains_on_free_form() -> None:
    state = review_state()
    state["sentiment_results"] = [
        {
            **state["sentiment_results"][0],
            "sample_id": "known",
            "text": "普通消费者最后还是要承担更高成本",
        },
        {
            **state["sentiment_results"][0],
            "sample_id": "free",
            "text": "一个未预置的新评论",
        },
    ]

    result = OfflineDemoReviewer().review(state)  # type: ignore[arg-type]

    assert result["items"][0]["label"] == "Negative"
    assert result["items"][0]["confidence"] == "High"
    assert result["items"][1]["confidence"] == "Low"
    assert result["reviewer"] == "offline_demo_replay_v1"
