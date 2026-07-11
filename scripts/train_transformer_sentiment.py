"""Fine-tune a Chinese Transformer sentiment classifier.

This script is intentionally self-contained and does not require the
`datasets` package. It consumes the JSONL files exported by
`scripts/export_transformer_dataset.py` and writes a Hugging Face-compatible
sequence-classification model that can be loaded by
`TransformerSentimentClassifier`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import argparse
import inspect
import json
import sys

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, f1_score
import torch
from torch.utils.data import Dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


LABELS = ["Negative", "Neutral", "Positive", "Unscorable"]
ID_TO_LABEL = {index: label for index, label in enumerate(LABELS)}
LABEL_TO_ID = {label: index for index, label in ID_TO_LABEL.items()}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class SentimentJsonlDataset(Dataset):
    def __init__(self, rows: list[dict[str, Any]], tokenizer: Any, max_length: int) -> None:
        self.rows = rows
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        row = self.rows[index]
        encoded = self.tokenizer(
            str(row["text"]),
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )
        item = {key: value.squeeze(0) for key, value in encoded.items()}
        item["labels"] = torch.tensor(int(row["label_id"]), dtype=torch.long)
        return item


@dataclass(frozen=True)
class MetricsBundle:
    accuracy: float
    macro_f1: float
    negative_recall: float


def compute_metrics(eval_prediction: Any) -> dict[str, float]:
    logits, labels = eval_prediction
    predictions = np.argmax(logits, axis=-1)
    report = classification_report(
        labels,
        predictions,
        labels=list(ID_TO_LABEL),
        target_names=LABELS,
        output_dict=True,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "negative_recall": float(report["Negative"]["recall"]),
    }


def compute_class_weights(rows: list[dict[str, Any]], num_labels: int) -> torch.Tensor:
    counts = Counter(int(row["label_id"]) for row in rows)
    total = sum(counts.values())
    weights = [
        total / (num_labels * counts[label_id]) if counts[label_id] else 0.0
        for label_id in range(num_labels)
    ]
    return torch.tensor(weights, dtype=torch.float)


def write_prediction_report(
    path: Path,
    rows: list[dict[str, Any]],
    logits: np.ndarray,
    labels: np.ndarray,
) -> None:
    predictions = np.argmax(logits, axis=-1)
    report = classification_report(
        labels,
        predictions,
        labels=list(ID_TO_LABEL),
        target_names=LABELS,
        output_dict=True,
        zero_division=0,
    )
    cases = []
    for row, prediction_id, label_id, logit_row in zip(rows, predictions, labels, logits):
        probabilities = torch.softmax(torch.tensor(logit_row), dim=-1).numpy()
        cases.append(
            {
                "sample_id": row.get("sample_id", ""),
                "text": row["text"],
                "gold_label": ID_TO_LABEL[int(label_id)],
                "predicted_label": ID_TO_LABEL[int(prediction_id)],
                "probabilities": {
                    ID_TO_LABEL[index]: float(probability)
                    for index, probability in enumerate(probabilities)
                },
                "correct": int(prediction_id) == int(label_id),
            }
        )

    output = {
        "labels": LABELS,
        "metrics": {
            "accuracy": float(accuracy_score(labels, predictions)),
            "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
            "negative_recall": float(report["Negative"]["recall"]),
        },
        "classification_report": report,
        "cases": cases,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def build_trainer_kwargs(
    trainer_cls: type,
    *,
    model: Any,
    training_args: Any,
    train_dataset: Dataset,
    validation_dataset: Dataset,
    tokenizer: Any,
) -> dict[str, Any]:
    """Build Trainer kwargs across Transformers tokenizer API versions."""

    kwargs: dict[str, Any] = {
        "model": model,
        "args": training_args,
        "train_dataset": train_dataset,
        "eval_dataset": validation_dataset,
        "compute_metrics": compute_metrics,
    }
    parameters = inspect.signature(trainer_cls.__init__).parameters
    if "processing_class" in parameters:
        kwargs["processing_class"] = tokenizer
    elif "tokenizer" in parameters:
        kwargs["tokenizer"] = tokenizer
    return kwargs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "modeling" / "transformer_sentiment",
    )
    parser.add_argument(
        "--model-name-or-path",
        default="hfl/chinese-roberta-wwm-ext",
        help="Local path or Hugging Face model id. Prefer a local path for reproducible offline runs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "transformer_sentiment_v1",
    )
    parser.add_argument("--max-length", type=int, default=192)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--class-weighting",
        choices=["none", "balanced"],
        default="none",
        help="Use balanced cross-entropy weights to improve minority-class learning.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate input files and print dataset sizes.",
    )
    args = parser.parse_args()

    train_rows = load_jsonl(args.data_dir / "train.jsonl")
    validation_rows = load_jsonl(args.data_dir / "validation.jsonl")
    test_rows = load_jsonl(args.data_dir / "test.jsonl")

    summary = {
        "train": len(train_rows),
        "validation": len(validation_rows),
        "test": len(test_rows),
        "labels": LABELS,
        "model_name_or_path": args.model_name_or_path,
        "output_dir": str(args.output_dir),
        "class_weighting": args.class_weighting,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    try:
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
            set_seed,
        )
    except ImportError as exc:
        raise ImportError(
            "Training requires `transformers` and a compatible `torch` installation."
        ) from exc

    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name_or_path,
        num_labels=len(LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )

    train_dataset = SentimentJsonlDataset(train_rows, tokenizer, args.max_length)
    validation_dataset = SentimentJsonlDataset(validation_rows, tokenizer, args.max_length)
    test_dataset = SentimentJsonlDataset(test_rows, tokenizer, args.max_length)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        weight_decay=args.weight_decay,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=20,
        report_to=[],
        seed=args.seed,
    )

    trainer_cls = Trainer
    class_weights = None
    if args.class_weighting == "balanced":
        class_weights = compute_class_weights(train_rows, len(LABELS))

        class WeightedLossTrainer(Trainer):
            def compute_loss(
                self,
                model: Any,
                inputs: dict[str, torch.Tensor],
                return_outputs: bool = False,
                num_items_in_batch: torch.Tensor | int | None = None,
            ) -> torch.Tensor | tuple[torch.Tensor, Any]:
                labels = inputs.get("labels")
                outputs = model(**inputs)
                logits = outputs["logits"] if isinstance(outputs, dict) else outputs.logits
                loss = torch.nn.functional.cross_entropy(
                    logits.view(-1, len(LABELS)),
                    labels.view(-1),  # type: ignore[union-attr]
                    weight=class_weights.to(logits.device),  # type: ignore[union-attr]
                )
                return (loss, outputs) if return_outputs else loss

        trainer_cls = WeightedLossTrainer

    trainer = trainer_cls(
        **build_trainer_kwargs(
            trainer_cls,
            model=model,
            training_args=training_args,
            train_dataset=train_dataset,
            validation_dataset=validation_dataset,
            tokenizer=tokenizer,
        )
    )
    trainer.train()
    validation_metrics = trainer.evaluate(validation_dataset)
    test_prediction = trainer.predict(test_dataset)

    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))

    report_path = args.output_dir / "test_metrics.json"
    write_prediction_report(
        report_path,
        test_rows,
        test_prediction.predictions,
        test_prediction.label_ids,
    )
    run_summary = {
        **summary,
        "validation_metrics": validation_metrics,
        "test_metrics_path": str(report_path),
        "limitations": [
            "Legacy CSV export is the first training source and is not the final gold-standard evaluation.",
            "Final claims should be re-run on repaired event-level partially adjudicated data.",
        ],
    }
    (args.output_dir / "training_summary.json").write_text(
        json.dumps(run_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
