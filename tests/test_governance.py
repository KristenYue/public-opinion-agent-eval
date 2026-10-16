import pytest

from opinion_agent.governance import (
    HumanConfirmationRequired,
    RequestBudgetExceeded,
    SecurityPolicy,
    ToolPolicyViolation,
    redact_sensitive,
    redact_sensitive_text,
)
from opinion_agent.evaluation.security_governance import evaluate_security_governance


def test_redaction_removes_direct_pii_and_credentials_recursively() -> None:
    payload = {
        "text": "联系 user@example.com 或 13812345678",
        "nested": ["api_key=top-secret-value", "Bearer abcdefghijklmnop"],
        "api_key": "short-secret-not-detectable-by-value-pattern",
    }

    redacted = redact_sensitive(payload)

    serialized = str(redacted)
    assert "user@example.com" not in serialized
    assert "13812345678" not in serialized
    assert "top-secret-value" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "short-secret-not-detectable-by-value-pattern" not in serialized
    assert "[REDACTED_EMAIL]" in serialized
    assert redact_sensitive_text("普通舆情文本") == "普通舆情文本"


def test_request_character_budget_fails_closed() -> None:
    policy = SecurityPolicy(max_request_chars=20)

    with pytest.raises(RequestBudgetExceeded, match="character budget exceeded"):
        policy.validate_request_payload({"query": "x" * 30})


def test_unknown_tool_and_tool_count_are_rejected() -> None:
    policy = SecurityPolicy(max_tool_calls=1, allowed_tools=frozenset({"safe_tool"}))

    with pytest.raises(ToolPolicyViolation, match="not allowlisted"):
        policy.validate_result({"tool_traces": [{"node": "unknown"}]})
    with pytest.raises(ToolPolicyViolation, match="budget exceeded"):
        policy.validate_result(
            {"tool_traces": [{"node": "safe_tool"}, {"node": "safe_tool"}]}
        )


def test_dangerous_tool_requires_explicit_human_confirmation() -> None:
    policy = SecurityPolicy(
        allowed_tools=frozenset({"publish_external_report"}),
        dangerous_tools=frozenset({"publish_external_report"}),
    )

    with pytest.raises(HumanConfirmationRequired, match="human confirmation"):
        policy.authorize_tool("publish_external_report")

    policy.authorize_tool("publish_external_report", human_confirmed=True)


def test_security_governance_gate_covers_ten_scenarios() -> None:
    report = evaluate_security_governance()

    assert report["status"] == "passed"
    assert report["scenario_count"] == 10
    assert report["passed_count"] == 10
