from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.sentiment.transformer_classifier import (  # noqa: E402
    TransformerClassifierConfig,
    prepare_transformer_text,
)


def test_transformer_preprocessing_matches_training_contract() -> None:
    text = "  太差了！ABC 😡  "

    assert prepare_transformer_text(text) == "太差了！ABC 😡"


def test_transformer_default_max_length_matches_training_run() -> None:
    config = TransformerClassifierConfig(model_path="unused")

    assert config.max_length == 192
