from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.evaluation import bootstrap_classification_metrics  # noqa: E402


def test_bootstrap_intervals_are_deterministic_and_contain_point_estimate() -> None:
    rows = [
        {"human_label": "Positive", "prediction": "Positive"},
        {"human_label": "Negative", "prediction": "Neutral"},
        {"human_label": "Neutral", "prediction": "Neutral"},
        {"human_label": "Positive", "prediction": "Negative"},
    ]

    first = bootstrap_classification_metrics(
        rows, "prediction", iterations=200, seed=7
    )
    second = bootstrap_classification_metrics(
        rows, "prediction", iterations=200, seed=7
    )

    assert first == second
    for metric in ("accuracy", "macro_f1"):
        values = first[metric]
        assert values["lower"] <= values["point_estimate"] <= values["upper"]
        assert 0.0 <= values["lower"] <= values["upper"] <= 1.0


def test_bootstrap_rejects_too_few_iterations() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        bootstrap_classification_metrics(
            [{"human_label": "Neutral", "prediction": "Neutral"}],
            "prediction",
            iterations=10,
        )
