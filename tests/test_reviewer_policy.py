from opinion_agent.evaluation.reviewer_policy import evaluate_override_policy


def test_gated_override_counts_corrections_and_harm() -> None:
    cases = [
        {"sample_id": "fix", "xgb_label": "Neutral", "expected_label": "Positive", "selection_reason": "model_disagreement"},
        {"sample_id": "harm", "xgb_label": "Neutral", "expected_label": "Neutral", "selection_reason": "short_text_context_risk"},
    ]
    responses = [
        {"sample_id": "fix", "label": "Positive", "confidence": "High"},
        {"sample_id": "harm", "label": "Positive", "confidence": "High"},
    ]

    metrics = evaluate_override_policy(
        cases,
        responses,
        allowed_confidence=frozenset({"High"}),
        allowed_reasons=frozenset({"model_disagreement"}),
    )

    assert metrics["overrides"] == 1
    assert metrics["corrected_errors"] == 1
    assert metrics["harmful_overrides"] == 0
    assert metrics["final_accuracy"] == 1.0
