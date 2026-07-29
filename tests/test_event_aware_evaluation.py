from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from evaluate_event_aware_cascade import (  # noqa: E402
    assert_event_isolation,
    event_level_breakdown,
    review_provenance,
    stratified_sample_bootstrap,
)


def test_event_isolation_accepts_one_split_per_event() -> None:
    assert assert_event_isolation(
        [
            {"event_id": "a", "split": "train"},
            {"event_id": "a", "split": "train"},
            {"event_id": "b", "split": "test"},
        ]
    ) == {"a": "train", "b": "test"}


def test_event_isolation_rejects_cross_split_event() -> None:
    with pytest.raises(ValueError, match="Event isolation violated"):
        assert_event_isolation(
            [
                {"event_id": "a", "split": "train"},
                {"event_id": "a", "split": "test"},
            ]
        )


def _bootstrap_rows() -> list[dict[str, object]]:
    return [
        {
            "sample_id": "e1-1",
            "event_id": "event-1",
            "content": "明确不满",
            "gold": "Negative",
            "xgb_label": "Neutral",
            "xgb_confidence": 0.6,
            "secondary_label": "Negative",
        },
        {
            "sample_id": "e1-2",
            "event_id": "event-1",
            "content": "我们明确支持这项措施",
            "gold": "Positive",
            "xgb_label": "Positive",
            "xgb_confidence": 0.9,
            "secondary_label": "Positive",
        },
        {
            "sample_id": "e2-1",
            "event_id": "event-2",
            "content": "仍然不满意",
            "gold": "Negative",
            "xgb_label": "Negative",
            "xgb_confidence": 0.9,
            "secondary_label": "Negative",
        },
        {
            "sample_id": "e2-2",
            "event_id": "event-2",
            "content": "继续支持",
            "gold": "Positive",
            "xgb_label": "Neutral",
            "xgb_confidence": 0.6,
            "secondary_label": "Positive",
        },
    ]


def _bootstrap_qwen() -> dict[str, dict[str, object]]:
    return {
        "e1-1": {"label": "Negative", "confidence": "High"},
        "e2-2": {"label": "Positive", "confidence": "High"},
    }


def test_sample_bootstrap_is_deterministic_and_bounded() -> None:
    kwargs = {
        "threshold": 0.8,
        "short_text_max_chars": 4,
        "resamples": 100,
        "seed": 7,
    }
    first = stratified_sample_bootstrap(  # type: ignore[arg-type]
        _bootstrap_rows(),
        _bootstrap_qwen(),
        **kwargs,
    )
    second = stratified_sample_bootstrap(  # type: ignore[arg-type]
        _bootstrap_rows(),
        _bootstrap_qwen(),
        **kwargs,
    )

    assert first == second
    assert first["scope"] == "conditional_on_the_current_frozen_test_events"
    for stage in first["intervals"].values():
        for interval in stage.values():
            assert 0.0 <= interval["lower"] <= interval["upper"] <= 1.0


def test_event_breakdown_preserves_held_out_event_boundaries() -> None:
    breakdown = event_level_breakdown(  # type: ignore[arg-type]
        _bootstrap_rows(),
        _bootstrap_qwen(),
        threshold=0.8,
        short_text_max_chars=4,
    )

    assert set(breakdown) == {"event-1", "event-2"}
    assert breakdown["event-1"]["samples"] == 2
    assert breakdown["event-2"]["samples"] == 2


def test_review_provenance_counts_only_evaluation_rows() -> None:
    reviews = {
        "train": {"needs_review": True},
        "validation": {
            "needs_review": False,
            "truth_status": "independent_second_pass_complete",
        },
        "test": {"needs_review": False},
    }

    provenance = review_provenance(reviews, {"validation", "test"})

    assert provenance == {
        "source": "second_pass_merged_reviews",
        "evaluated_rows": 2,
        "second_pass_adjudicated_rows": 1,
        "pending_second_pass_rows": 0,
    }
