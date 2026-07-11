from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from train_transformer_sentiment import build_trainer_kwargs, compute_class_weights  # noqa: E402


class NewTrainer:
    def __init__(self, *, processing_class=None, **kwargs):
        pass


class OldTrainer:
    def __init__(self, *, tokenizer=None, **kwargs):
        pass


def test_build_trainer_kwargs_uses_processing_class_for_new_transformers() -> None:
    tokenizer = object()

    kwargs = build_trainer_kwargs(
        NewTrainer,
        model=object(),
        training_args=object(),
        train_dataset=object(),  # type: ignore[arg-type]
        validation_dataset=object(),  # type: ignore[arg-type]
        tokenizer=tokenizer,
    )

    assert kwargs["processing_class"] is tokenizer
    assert "tokenizer" not in kwargs


def test_build_trainer_kwargs_uses_tokenizer_for_old_transformers() -> None:
    tokenizer = object()

    kwargs = build_trainer_kwargs(
        OldTrainer,
        model=object(),
        training_args=object(),
        train_dataset=object(),  # type: ignore[arg-type]
        validation_dataset=object(),  # type: ignore[arg-type]
        tokenizer=tokenizer,
    )

    assert kwargs["tokenizer"] is tokenizer
    assert "processing_class" not in kwargs


def test_compute_class_weights_prioritizes_minority_labels() -> None:
    rows = [
        {"label_id": 0},
        {"label_id": 1},
        {"label_id": 2},
        {"label_id": 2},
        {"label_id": 2},
    ]

    weights = compute_class_weights(rows, num_labels=4)

    assert weights[0] > weights[2]
    assert weights[3] == 0.0
