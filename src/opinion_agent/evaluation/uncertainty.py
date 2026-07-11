"""Deterministic uncertainty estimates for small held-out evaluation sets."""

from collections.abc import Sequence
import random

import numpy as np
from sklearn.metrics import accuracy_score, f1_score

from .baselines import LABELS, normalize_prediction


def bootstrap_classification_metrics(
    rows: Sequence[dict[str, object]],
    prediction_column: str,
    *,
    iterations: int = 5000,
    seed: int = 20260628,
    confidence_level: float = 0.95,
) -> dict[str, object]:
    """Estimate percentile intervals by resampling held-out comment rows."""
    if not rows:
        raise ValueError("At least one evaluation row is required")
    if iterations < 100:
        raise ValueError("iterations must be at least 100")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")

    truth = [str(row["human_label"]) for row in rows]
    predictions = [normalize_prediction(row[prediction_column]) for row in rows]
    rng = random.Random(seed)
    accuracies: list[float] = []
    macro_f1_scores: list[float] = []
    sample_size = len(rows)

    for _ in range(iterations):
        indices = [rng.randrange(sample_size) for _ in range(sample_size)]
        sampled_truth = [truth[index] for index in indices]
        sampled_predictions = [predictions[index] for index in indices]
        accuracies.append(accuracy_score(sampled_truth, sampled_predictions))
        macro_f1_scores.append(
            f1_score(
                sampled_truth,
                sampled_predictions,
                labels=LABELS,
                average="macro",
                zero_division=0,
            )
        )

    alpha = (1.0 - confidence_level) / 2.0

    def summarize(point: float, samples: list[float]) -> dict[str, float]:
        lower, upper = np.quantile(samples, [alpha, 1.0 - alpha])
        return {
            "point_estimate": point,
            "lower": float(lower),
            "upper": float(upper),
        }

    return {
        "samples": sample_size,
        "iterations": iterations,
        "seed": seed,
        "confidence_level": confidence_level,
        "method": "row_level_nonparametric_percentile_bootstrap",
        "accuracy": summarize(accuracy_score(truth, predictions), accuracies),
        "macro_f1": summarize(
            f1_score(
                truth,
                predictions,
                labels=LABELS,
                average="macro",
                zero_division=0,
            ),
            macro_f1_scores,
        ),
        "limitation": (
            "Rows are resampled independently; the interval does not estimate uncertainty "
            "across unseen events because the test split contains only two events."
        ),
    }
