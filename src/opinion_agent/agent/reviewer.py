"""Structured LLM reviewer with a resilient OpenAI-compatible interface."""

from collections.abc import Callable
from hashlib import sha256
from time import sleep
from typing import Any, Literal
import json

import httpx
from pydantic import BaseModel, Field, field_validator

from .state import AgentState, ReviewResult


REVIEW_SHORT_TEXT_MAX_CHARS = 4


def review_selection_reason(result: dict[str, object]) -> str | None:
    """Select observable comment-level risks without using a human label."""
    if str(result.get("label", "")) == "Unscorable":
        return "unscorable"
    if result.get("models_agree") is False:
        return "model_disagreement"
    if len(str(result.get("text", "")).strip()) <= REVIEW_SHORT_TEXT_MAX_CHARS:
        return "short_text_context_risk"
    return None


class ReviewItemModel(BaseModel):
    sample_id: str
    label: Literal["Positive", "Neutral", "Negative", "Unscorable"]
    rationale: str = Field(min_length=1, max_length=300)
    confidence: Literal["High", "Medium", "Low"]

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> object:
        """Accept common provider variants while preserving the internal contract."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score = float(value)
            if not 0.0 <= score <= 1.0:
                return value
            return "High" if score >= 0.8 else "Medium" if score >= 0.5 else "Low"
        if isinstance(value, str):
            normalized = value.strip().lower()
            return {"high": "High", "medium": "Medium", "low": "Low"}.get(
                normalized, value
            )
        return value

    @field_validator("rationale", mode="before")
    @classmethod
    def bound_rationale(cls, value: object) -> object:
        if isinstance(value, str) and len(value) > 300:
            return value[:300].rstrip()
        return value


class ReviewBatchModel(BaseModel):
    items: list[ReviewItemModel]
    summary: str = Field(min_length=1, max_length=500)


class OpenAICompatibleReviewer:
    """Review selected high-risk comments and require validated JSON output."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        max_input_chars: int = 50000,
        post_func: Callable[..., httpx.Response] | None = None,
        sleep_func: Callable[[float], None] = sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if max_input_chars < 1:
            raise ValueError("max_input_chars must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.max_input_chars = max_input_chars
        self.post_func = post_func or httpx.post
        self.sleep_func = sleep_func

    def review(self, state: AgentState) -> ReviewResult:
        selected = [
            result
            for result in state.get("sentiment_results", [])
            if review_selection_reason(result) is not None
        ]
        if not selected:
            raise ValueError("Review route triggered without selected comment-level items")
        context_by_id = {
            str(comment.get("sample_id", "")): {
                "context": comment.get("context", ""),
                "source_url": comment.get("source_url", ""),
            }
            for comment in state.get("comments", [])
        }
        review_comments = [
            {
                **result,
                **context_by_id.get(result["sample_id"], {}),
            }
            for result in selected
        ]
        payload = {
            "event_id": state["event_id"],
            "task": state["query"],
            "comments": review_comments,
            "retrieved_evidence": state.get("retrieved_evidence", []),
            "label_rules": {
                "Positive": "clear praise, support, liking, optimism or positive emotion",
                "Negative": "clear criticism, opposition, anger, disappointment or concern",
                "Neutral": "factual statement, question, information or no clear valence",
                "Unscorable": "meaningless, context is insufficient or unrelated",
            },
        }
        request_body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Chinese sentiment adjudicator. Return JSON with keys "
                        "items and summary. Each item must contain sample_id, label, "
                        "rationale and confidence. confidence MUST be exactly one of the "
                        "strings High, Medium or Low (never a number); rationale MUST be "
                        "300 characters or fewer. Use each comment's context when present. "
                        "Review every supplied comment exactly once, preserve sample_id, "
                        "and never invent missing evidence."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        input_chars = len(json.dumps(request_body, ensure_ascii=False))
        if input_chars > self.max_input_chars:
            raise ValueError(
                f"Reviewer input budget exceeded: {input_chars}>{self.max_input_chars} chars"
            )
        selected_ids = [str(item["sample_id"]) for item in selected]
        idempotency_key = sha256(
            f"{state.get('request_id', '')}:{','.join(selected_ids)}".encode("utf-8")
        ).hexdigest()
        response, attempts = self._post_with_retry(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Idempotency-Key": idempotency_key,
            },
            request_body=request_body,
        )
        response_data = response.json()
        content = response_data["choices"][0]["message"]["content"]
        parsed = ReviewBatchModel.model_validate_json(_strip_code_fence(content))
        returned_ids = [item.sample_id for item in parsed.items]
        duplicate_ids = sorted(
            sample_id for sample_id in set(returned_ids) if returned_ids.count(sample_id) > 1
        )
        missing_ids = sorted(set(selected_ids) - set(returned_ids))
        unexpected_ids = sorted(set(returned_ids) - set(selected_ids))
        if duplicate_ids or missing_ids or unexpected_ids:
            raise ValueError(
                "Reviewer item contract violated: "
                f"missing={missing_ids}, unexpected={unexpected_ids}, duplicates={duplicate_ids}"
            )
        raw_usage = response_data.get("usage", {})
        usage = {
            "prompt_tokens": int(raw_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(raw_usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(raw_usage.get("total_tokens", 0) or 0),
            "input_chars": input_chars,
        }
        return {
            "items": [item.model_dump() for item in parsed.items],  # type: ignore[misc]
            "summary": parsed.summary,
            "reviewer": self.model,
            "usage": usage,
            "attempts": attempts,
            "idempotency_key": idempotency_key,
        }

    def _post_with_retry(
        self,
        *,
        headers: dict[str, str],
        request_body: dict[str, Any],
    ) -> tuple[httpx.Response, int]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.post_func(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=request_body,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response, attempt
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                if not retryable or attempt == self.max_attempts:
                    raise
                retry_after = _retry_after_seconds(
                    exc.response if isinstance(exc, httpx.HTTPStatusError) else None
                )
                delay = max(retry_after, self.backoff_seconds * (2 ** (attempt - 1)))
                self.sleep_func(delay)
        assert last_error is not None
        raise last_error


def _strip_code_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1]
        value = value.rsplit("```", 1)[0]
    return value.strip()


def _retry_after_seconds(response: httpx.Response | None) -> float:
    if response is None:
        return 0.0
    value = response.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 0.0), 30.0)
    except ValueError:
        return 0.0
