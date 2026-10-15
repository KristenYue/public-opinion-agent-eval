"""Deterministic trust boundary for untrusted retrieval documents."""

from __future__ import annotations

import re
from typing import Any


_INJECTION_PATTERNS = {
    "ignore_instructions": re.compile(
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions|"
        r"忽略(?:之前|以上|前面|所有)(?:的)?(?:所有)?(?:指令|规则|要求)",
        re.IGNORECASE,
    ),
    "system_prompt_exfiltration": re.compile(
        r"system\s+prompt|reveal\s+(?:the\s+)?(?:prompt|secret)|"
        r"(?:输出|泄露|显示)(?:系统)?(?:提示词|密钥|api\s*key)",
        re.IGNORECASE,
    ),
    "role_override": re.compile(
        r"you\s+are\s+now|act\s+as\s+(?:an?|the)|"
        r"你现在是|扮演(?:一个|成)?",
        re.IGNORECASE,
    ),
    "tool_command": re.compile(
        r"(?:call|execute|invoke)\s+(?:the\s+)?(?:tool|function)|"
        r"(?:调用|执行)(?:危险|删除|转账|发信|工具)",
        re.IGNORECASE,
    ),
}


def detect_prompt_injection(text: str) -> list[str]:
    """Return stable rule identifiers; never execute or echo the instruction."""

    return [name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(text)]


class GuardedRetriever:
    """Filter instruction-like evidence before it enters an LLM payload."""

    def __init__(self, retriever: Any, candidate_multiplier: int = 3) -> None:
        if candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be at least 1")
        self.retriever = retriever
        self.candidate_multiplier = candidate_multiplier
        self.last_rejections: list[dict[str, object]] = []

    def __getattr__(self, name: str):
        return getattr(self.retriever, name)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        exclude_event_id: str | None = None,
    ) -> list[dict[str, object]]:
        candidates = self.retriever.retrieve(
            query,
            top_k=max(top_k, top_k * self.candidate_multiplier),
            exclude_event_id=exclude_event_id,
        )
        accepted: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        for item in candidates:
            reasons = detect_prompt_injection(str(item.get("text", "")))
            if reasons:
                rejected.append(
                    {
                        "evidence_id": item.get("evidence_id"),
                        "event_id": item.get("event_id"),
                        "reasons": reasons,
                    }
                )
                continue
            accepted.append(item)
            if len(accepted) >= top_k:
                break
        self.last_rejections = rejected
        return accepted
