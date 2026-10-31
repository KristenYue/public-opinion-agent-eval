"""Runtime safety policy shared by HTTP jobs, workers, and MCP entrypoints."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Mapping


DEFAULT_ALLOWED_TOOLS = frozenset(
    {
        "sentiment_classifier",
        "sentiment_aggregator",
        "evidence_retriever",
        "review_router",
        "review_required",
        "llm_review",
        "baseline_ready",
        "human_review",
        "briefing_composer",
    }
)


class SecurityPolicyError(ValueError):
    """Base class for a fail-closed governance decision."""


class RequestBudgetExceeded(SecurityPolicyError):
    """The normalized request exceeds its configured character budget."""


class ToolPolicyViolation(SecurityPolicyError):
    """A result contains an unknown or over-budget tool trajectory."""


class HumanConfirmationRequired(SecurityPolicyError):
    """A side-effecting tool was requested without explicit approval."""


_SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_API_KEY]"),
    (
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        re.compile(
            r"\b(api[_-]?key|access[_-]?token|password|cookie)\s*[:=]\s*[^\s&;]+",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?<![\w.])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.])"),
        "[REDACTED_EMAIL]",
    ),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[REDACTED_PHONE]"),
)
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "cookie",
        "set_cookie",
        "client_secret",
    }
)


def redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_sensitive(value: Any) -> Any:
    """Return a JSON-compatible copy with secrets and direct PII removed."""

    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized_key = key_text.strip().lower().replace("-", "_")
            redacted[key_text] = (
                "[REDACTED]"
                if normalized_key in _SENSITIVE_FIELD_NAMES
                else redact_sensitive(item)
            )
        return redacted
    return value


@dataclass(frozen=True)
class SecurityPolicy:
    max_request_chars: int = 100_000
    max_tool_calls: int = 8
    allowed_tools: frozenset[str] = field(default_factory=lambda: DEFAULT_ALLOWED_TOOLS)
    dangerous_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.max_request_chars < 1:
            raise ValueError("max_request_chars must be positive")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be positive")
        if not self.dangerous_tools <= self.allowed_tools:
            raise ValueError("dangerous tools must also be explicitly allowlisted")

    @classmethod
    def from_env(cls) -> "SecurityPolicy":
        return cls(
            max_request_chars=int(os.getenv("MAX_REQUEST_CHARS", "100000")),
            max_tool_calls=int(os.getenv("MAX_TOOL_CALLS", "8")),
        )

    def validate_request_payload(self, payload: Mapping[str, Any]) -> None:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        if len(serialized) > self.max_request_chars:
            raise RequestBudgetExceeded(
                f"request character budget exceeded: {len(serialized)}>{self.max_request_chars}"
            )

    def authorize_tool(self, tool_name: str, *, human_confirmed: bool = False) -> None:
        if tool_name not in self.allowed_tools:
            raise ToolPolicyViolation(f"tool is not allowlisted: {tool_name}")
        if tool_name in self.dangerous_tools and not human_confirmed:
            raise HumanConfirmationRequired(
                f"tool requires explicit human confirmation: {tool_name}"
            )

    def validate_result(self, result: Mapping[str, Any]) -> None:
        traces = result.get("tool_traces", [])
        if not isinstance(traces, list):
            raise ToolPolicyViolation("tool_traces must be a list")
        if len(traces) > self.max_tool_calls:
            raise ToolPolicyViolation(
                f"tool call budget exceeded: {len(traces)}>{self.max_tool_calls}"
            )
        for trace in traces:
            if not isinstance(trace, Mapping):
                raise ToolPolicyViolation("every tool trace must be an object")
            self.authorize_tool(str(trace.get("node", "")))

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_request_chars": self.max_request_chars,
            "max_tool_calls": self.max_tool_calls,
            "allowed_tools": sorted(self.allowed_tools),
            "dangerous_tools": sorted(self.dangerous_tools),
            "redaction_profile": "direct_pii_and_credentials_v1",
        }
