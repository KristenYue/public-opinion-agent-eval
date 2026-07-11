"""Stable inference wrapper for the legacy three-class XGBoost model."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import __main__

import joblib
import numpy as np

from .preprocessing import clean_text
from .tokenizer import jieba_tokenizer


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    probabilities: dict[str, float]
    cleaned_text: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SentimentClassifier:
    """Load the verified thesis assets and expose deterministic inference."""

    model_name = "legacy_xgboost"

    def __init__(self, artifacts_dir: str | Path) -> None:
        artifacts = Path(artifacts_dir).resolve()
        self.artifacts_dir = artifacts
        model_path = artifacts / "xgboost_sentiment_model.joblib"
        vectorizer_path = artifacts / "tfidf_vectorizer.joblib"
        encoder_path = artifacts / "label_encoder.joblib"

        missing = [str(path) for path in (model_path, vectorizer_path, encoder_path) if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing sentiment assets: {missing}")

        # The legacy vectorizer serialized this function under __main__.
        if not hasattr(__main__, "jieba_tokenizer"):
            setattr(__main__, "jieba_tokenizer", jieba_tokenizer)

        self.model = joblib.load(model_path)
        self.vectorizer = joblib.load(vectorizer_path)
        self.encoder = joblib.load(encoder_path)
        self._validate_assets()

    def _validate_assets(self) -> None:
        model_features = int(self.model.n_features_in_)
        vectorizer_features = len(self.vectorizer.get_feature_names_out())
        if model_features != vectorizer_features:
            raise ValueError(
                f"Model expects {model_features} features, vectorizer provides {vectorizer_features}"
            )
        if len(self.encoder.classes_) != len(self.model.classes_):
            raise ValueError("Label encoder and model class counts do not match")

    @property
    def labels(self) -> list[str]:
        return [str(label) for label in self.encoder.classes_]

    def predict(self, text: str) -> Prediction:
        return self.predict_many([text])[0]

    def predict_many(self, texts: Iterable[str]) -> list[Prediction]:
        original = list(texts)
        if not original:
            return []
        cleaned = [clean_text(text) for text in original]
        if any(not text for text in cleaned):
            raise ValueError("Text is empty after preprocessing")

        features = self.vectorizer.transform(cleaned)
        probabilities = self.model.predict_proba(features)
        encoded_predictions = np.asarray(self.model.predict(features), dtype=int)
        labels = self.encoder.inverse_transform(encoded_predictions)

        results: list[Prediction] = []
        for cleaned_text, label, row in zip(cleaned, labels, probabilities):
            probability_map = {
                class_name: float(probability)
                for class_name, probability in zip(self.labels, row)
            }
            results.append(
                Prediction(
                    label=str(label),
                    confidence=float(np.max(row)),
                    probabilities=probability_map,
                    cleaned_text=cleaned_text,
                )
            )
        return results
