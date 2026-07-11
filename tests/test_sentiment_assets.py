from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.sentiment import SentimentClassifier  # noqa: E402


def test_legacy_sentiment_assets_load_and_predict() -> None:
    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    prediction = classifier.predict("这个活动很好，我很喜欢")

    assert prediction.label in {"Positive", "Neutral", "Negative"}
    assert 0.0 <= prediction.confidence <= 1.0
    assert set(prediction.probabilities) == {"Positive", "Neutral", "Negative"}
