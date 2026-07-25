from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from evaluate_event_aware_cascade import assert_event_isolation  # noqa: E402


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
