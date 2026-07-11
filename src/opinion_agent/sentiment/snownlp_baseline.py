"""Secondary lexical sentiment signal used for disagreement routing."""

from dataclasses import dataclass

from snownlp import SnowNLP


@dataclass(frozen=True)
class SecondaryPrediction:
    label: str
    score: float


class SnowNLPSentimentClassifier:
    """Map SnowNLP's positive score to the legacy three-class label space."""

    def __init__(self, negative_threshold: float = 0.35, positive_threshold: float = 0.65) -> None:
        if not 0 < negative_threshold < positive_threshold < 1:
            raise ValueError("SnowNLP thresholds must satisfy 0 < negative < positive < 1")
        self.negative_threshold = negative_threshold
        self.positive_threshold = positive_threshold

    def predict(self, text: str) -> SecondaryPrediction:
        value = text.strip()
        if not value:
            return SecondaryPrediction("Unscorable", 0.0)
        score = float(SnowNLP(value).sentiments)
        if score > self.positive_threshold:
            label = "Positive"
        elif score < self.negative_threshold:
            label = "Negative"
        else:
            label = "Neutral"
        return SecondaryPrediction(label, score)
