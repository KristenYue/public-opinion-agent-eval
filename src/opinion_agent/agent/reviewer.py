"""Structured LLM reviewer with a resilient OpenAI-compatible interface."""

from collections.abc import Callable
from hashlib import sha256
from time import sleep
from typing import Any, Literal
import json
import os

import httpx
from pydantic import BaseModel, Field, field_validator

from .state import AgentState, ReviewResult


REVIEW_SHORT_TEXT_MAX_CHARS = 4
REVIEW_CONFIDENCE_THRESHOLD = 0.65
REVIEW_PROMPT_VERSION = "event_stance_v2"
OFFLINE_DEMO_EXPECTED = {
    "一天一个变化，完全是在折腾普通消费者": (
        "Negative",
        "评论明确批评政策变化频繁，并认为其折腾普通消费者。",
    ),
    "呵呵，真是太贴心了，又让普通人多花钱": (
        "Negative",
        "“呵呵”和“太贴心了”构成反讽，实际批评政策增加普通人负担。",
    ),
    "普通消费者最后还是要承担更高成本": (
        "Negative",
        "评论明确担忧政策成本最终转嫁给普通消费者。",
    ),
    "先看看后续具体实施细则": (
        "Neutral",
        "评论表示继续观察，没有明确支持或反对。",
    ),
    "又变了": (
        "Negative",
        "结合政策频繁调整的背景，评论表达不满。",
    ),
    "这项调整对国内企业可能是机会": (
        "Positive",
        "评论认为调整可能为国内企业带来机会。",
    ),
    "政策一天一个样，完全看不懂": (
        "Negative",
        "评论明确批评政策变化频繁且难以理解。",
    ),
}


def review_selection_reasons(result: dict[str, object]) -> list[str]:
    """Return every observable reason for escalating one comment."""

    confidence_threshold = float(
        os.getenv("REVIEW_CONFIDENCE_THRESHOLD", str(REVIEW_CONFIDENCE_THRESHOLD))
    )
    short_text_max_chars = int(
        os.getenv("REVIEW_SHORT_TEXT_MAX_CHARS", str(REVIEW_SHORT_TEXT_MAX_CHARS))
    )
    reasons: list[str] = []
    if result.get("force_qwen_evaluation") is True:
        reasons.append("offline_evaluation_candidate")
    if str(result.get("label", "")) == "Unscorable":
        reasons.append("unscorable")
    if result.get("models_agree") is False:
        reasons.append("model_disagreement")
    confidence = float(result.get("confidence", 0.0) or 0.0)
    if "confidence" in result and confidence < confidence_threshold:
        reasons.append("low_primary_confidence")
    if len(str(result.get("text", "")).strip()) <= short_text_max_chars:
        reasons.append("short_text_context_risk")
    return reasons


def review_selection_reason(result: dict[str, object]) -> str | None:
    """Select observable comment-level risks without using a human label."""
    reasons = review_selection_reasons(result)
    return reasons[0] if reasons else None


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

    @field_validator("summary", mode="before")
    @classmethod
    def bound_summary(cls, value: object) -> object:
        """Keep verbose provider summaries from discarding valid item labels."""
        if isinstance(value, str) and len(value) > 500:
            return value[:500].rstrip()
        return value


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
            if review_selection_reasons(result)
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
                "review_reasons": review_selection_reasons(result),
            }
            for result in selected
        ]
        payload = {
            "prompt_version": REVIEW_PROMPT_VERSION,
            "event_id": state["event_id"],
            "task": state["query"],
            "comments": review_comments,
            "retrieved_evidence": state.get("retrieved_evidence", []),
            "label_rules": {
                "Positive": "评论本身对事件目标有明确赞扬、支持、喜爱、满意或乐观表达",
                "Negative": "评论本身对事件目标有明确批评、反对、愤怒、失望、担忧或不满表达",
                "Neutral": "事实陈述、转述、询问、信息补充，或没有明确褒贬；事件本身是喜讯不等于评论为正面",
                "Unscorable": "无意义、与目标无关，或即使结合原帖仍无法确定指向和立场",
            },
            "decision_rules": [
                "只判断评论对事件目标的立场，不判断事件或原帖自身的总体情绪。",
                "不得把原帖的正面或负面氛围自动继承给评论。",
                "没有明确评价词的事实描述、人物名称、比分、时间、地点和疑问句优先判 Neutral。",
                "只有出现可归因于目标的明确褒贬证据，才判 Positive 或 Negative。",
                "反问、讽刺、否定和网络口语需结合原帖上下文解释；证据不足判 Unscorable。",
                "短回复必须结合 context；若“支持”“失望”等指向明确可判极性，否则不要猜测。",
            ],
            "calibration_examples": [
                {
                    "target": "某项公共服务政策",
                    "comment": "什么时候开始执行？",
                    "label": "Neutral",
                    "reason": "询问执行时间，没有表达支持或反对。",
                },
                {
                    "target": "某项公共服务政策",
                    "comment": "终于改了，这次必须支持。",
                    "label": "Positive",
                    "reason": "对政策调整有明确肯定和支持。",
                },
                {
                    "target": "某平台整改措施",
                    "comment": "说得好听，实际还是在压榨司机。",
                    "label": "Negative",
                    "reason": "对整改效果和平台行为有明确批评。",
                },
                {
                    "target": "某运动员夺冠表现",
                    "comment": "决赛比分是3比0。",
                    "label": "Neutral",
                    "reason": "仅陈述比赛事实，不能因夺冠背景判为正面。",
                },
                {
                    "target": "某运动员夺冠表现",
                    "comment": "配合太精彩了，实至名归！",
                    "label": "Positive",
                    "reason": "对表现有明确赞扬。",
                },
            ],
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
                        "300 characters or fewer. Follow decision_rules strictly. Judge the "
                        "comment's stance toward the event target, not the emotional tone of "
                        "the event or source post. Use context only to resolve reference, "
                        "negation, sarcasm and short replies. A factual statement remains "
                        "Neutral even when the event itself is positive or negative. "
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
            "prompt_version": REVIEW_PROMPT_VERSION,
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
                    if isinstance(exc, httpx.HTTPStatusError):
                        detail = _provider_error_detail(exc.response)
                        raise RuntimeError(
                            "Reviewer API request rejected: "
                            f"HTTP {exc.response.status_code}; provider_response={detail}"
                        ) from exc
                    raise
                retry_after = _retry_after_seconds(
                    exc.response if isinstance(exc, httpx.HTTPStatusError) else None
                )
                delay = max(retry_after, self.backoff_seconds * (2 ** (attempt - 1)))
                self.sleep_func(delay)
        assert last_error is not None
        raise last_error


class OfflineDemoReviewer:
    """Replay the frozen public example; abstain on every free-form input."""

    model = "offline_demo_replay_v1"

    def review(self, state: AgentState) -> ReviewResult:
        selected = [
            result
            for result in state.get("sentiment_results", [])
            if review_selection_reasons(result)
        ]
        if not selected:
            raise ValueError("Offline demo route triggered without selected items")
        items = []
        replayed = 0
        for result in selected:
            text = str(result.get("text", "")).strip()
            expected = OFFLINE_DEMO_EXPECTED.get(text)
            if expected is None:
                items.append(
                    {
                        "sample_id": str(result["sample_id"]),
                        "label": result["label"],
                        "rationale": (
                            "未配置在线 Qwen；自由输入不使用离线样例答案，需人工复核。"
                        ),
                        "confidence": "Low",
                    }
                )
                continue
            replayed += 1
            label, rationale = expected
            items.append(
                {
                    "sample_id": str(result["sample_id"]),
                    "label": label,
                    "rationale": rationale,
                    "confidence": "High",
                }
            )
        return {
            "items": items,  # type: ignore[typeddict-item]
            "summary": (
                f"离线验收样例回放 {replayed} 条；"
                f"自由输入人工兜底 {len(items) - replayed} 条。"
            ),
            "reviewer": self.model,
            "prompt_version": "offline_demo_replay_v1",
        }


def _strip_code_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1]
        value = value.rsplit("```", 1)[0]
    return value.strip()


def _provider_error_detail(response: httpx.Response, max_chars: int = 1000) -> str:
    """Expose a bounded provider error without request headers or credentials."""
    try:
        detail = json.dumps(response.json(), ensure_ascii=False)
    except (json.JSONDecodeError, UnicodeDecodeError):
        detail = response.text
    return detail[:max_chars]


def _retry_after_seconds(response: httpx.Response | None) -> float:
    if response is None:
        return 0.0
    value = response.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 0.0), 30.0)
    except ValueError:
        return 0.0
