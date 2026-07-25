"""Optional Transformer sentiment classifier adapter.

This module is intentionally small and dependency-light at import time.  The
project can still run the legacy baseline without `torch`/`transformers`, while
the internship-grade path can plug in a fine-tuned Chinese Transformer model
through the same `predict` / `predict_many` contract used by the LangGraph node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .classifier import Prediction


DEFAULT_LABEL_MAP = {
    "negative": "Negative",
    "neutral": "Neutral",
    "positive": "Positive",
    "exclude": "Unscorable",
    "unscorable": "Unscorable",
    "LABEL_0": "Negative",
    "LABEL_1": "Neutral",
    "LABEL_2": "Positive",
    "LABEL_3": "Unscorable",
}

EXPECTED_ID2LABEL = {
    0: "Negative",
    1: "Neutral",
    2: "Positive",
    3: "Unscorable",
}


def prepare_transformer_text(text: object) -> str:
    """Match training-time preprocessing: preserve content and trim only edges."""

    return "" if text is None else str(text).strip()


@dataclass(frozen=True)
class TransformerClassifierConfig:
    """Runtime configuration for a local or Hugging Face sequence classifier."""

    model_path: str | Path
    label_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_LABEL_MAP))
    model_name: str = "transformer_sentiment_v1"
    # scripts/train_transformer_sentiment.py trained the released v2 artifact at 192.
    max_length: int = 192
    device: int = -1


class TransformerSentimentClassifier:
    """Adapter that exposes Transformer predictions with the legacy contract.

    Expected model type: a Hugging Face-compatible text classification model,
    ideally fine-tuned on the project's Chinese public-opinion labels.

    The class is not wired into the API by default yet.  That is deliberate:
    XGBoost remains the reproducible baseline, and this adapter is the stable
    seam for the upgraded classifier once model weights are trained or selected.
    """

    def __init__(self, config: TransformerClassifierConfig) -> None:
        self.config = config
        self.model_name = config.model_name
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover - exercised only without optional deps
            raise ImportError(
                "TransformerSentimentClassifier requires optional dependency "
                "`transformers`. Install it together with a compatible torch build "
                "before enabling the upgraded classifier."
            ) from exc

        self._pipeline = pipeline(
            task="text-classification",
            model=str(config.model_path),
            tokenizer=str(config.model_path),
            top_k=None,
            truncation=True,
            max_length=config.max_length,
            device=config.device,
        )
        self._validate_model_labels()

    def _validate_model_labels(self) -> None:
        """Fail fast instead of silently attaching the wrong label order."""

        raw_mapping = getattr(self._pipeline.model.config, "id2label", {})
        actual = {int(index): str(label) for index, label in raw_mapping.items()}
        if actual != EXPECTED_ID2LABEL:
            raise ValueError(
                "Transformer id2label does not match the training contract: "
                f"expected={EXPECTED_ID2LABEL}, actual={actual}"
            )
        self.id2label = actual

    @property
    def labels(self) -> list[str]:
        return ["Negative", "Neutral", "Positive", "Unscorable"]

    def predict(self, text: str) -> Prediction:
        return self.predict_many([text])[0]

    def predict_many(self, texts: Iterable[str]) -> list[Prediction]:
        original = list(texts)
        if not original:
            return []

        prepared = [prepare_transformer_text(text) for text in original]
        if any(not text for text in prepared):
            raise ValueError("Text is empty after preprocessing")

        raw_outputs = self._pipeline(prepared)
        return [
            self._convert_output(prepared_text, output)
            for prepared_text, output in zip(prepared, raw_outputs)
        ]

    def _convert_output(self, cleaned_text: str, output: object) -> Prediction:
        rows = output if isinstance(output, list) else [output]
        probabilities: dict[str, float] = {label: 0.0 for label in self.labels}

        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_label = str(row.get("label", ""))
            label = self.config.label_map.get(raw_label, raw_label)
            if label not in probabilities:
                continue
            probabilities[label] = float(row.get("score", 0.0))

        label = max(probabilities, key=probabilities.get)
        return Prediction(
            label=label,
            confidence=probabilities[label],
            probabilities=probabilities,
            cleaned_text=cleaned_text,
        )
