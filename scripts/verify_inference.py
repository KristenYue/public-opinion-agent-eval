"""Compare the frozen offline Transformer with the deployment inference chain."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import argparse
import hashlib
import json
import sys

import torch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.sentiment import SentimentClassifier  # noqa: E402
from opinion_agent.sentiment.transformer_classifier import (  # noqa: E402
    EXPECTED_ID2LABEL,
    TransformerClassifierConfig,
    TransformerSentimentClassifier,
    prepare_transformer_text,
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def select_gold(rows: list[dict[str, Any]], per_label: int) -> list[dict[str, Any]]:
    """Take the first N rows per label without selecting on model correctness."""

    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        label = str(row["label"])
        if counts[label] >= per_label:
            continue
        selected.append(row)
        counts[label] += 1
    return selected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def direct_predictions(classifier: TransformerSentimentClassifier, texts: list[str]):
    """Reproduce training/evaluation inference on the unmodified text."""

    pipeline = classifier._pipeline
    tokenizer = pipeline.tokenizer
    model = pipeline.model
    encoded = tokenizer(
        texts,
        truncation=True,
        padding="max_length",
        max_length=classifier.config.max_length,
        return_tensors="pt",
    )
    device = next(model.parameters()).device
    encoded = {key: value.to(device) for key, value in encoded.items()}
    model.eval()
    with torch.no_grad():
        probabilities = torch.softmax(model(**encoded).logits, dim=-1).cpu()

    predictions = []
    for row in probabilities:
        label_id = int(torch.argmax(row).item())
        predictions.append(
            {
                "label_id": label_id,
                "label": EXPECTED_ID2LABEL[label_id],
                "probabilities": {
                    EXPECTED_ID2LABEL[index]: float(score)
                    for index, score in enumerate(row.tolist())
                },
            }
        )
    return predictions


def accuracy(cases: list[dict[str, Any]], key: str) -> float:
    return sum(case[key] == case["gold"] for case in cases) / len(cases)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gold",
        type=Path,
        default=PROJECT_ROOT / "data" / "modeling" / "transformer_sentiment" / "test.jsonl",
    )
    parser.add_argument(
        "--transformer-model",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "transformer_sentiment_v2_weighted",
    )
    parser.add_argument(
        "--legacy-artifacts",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "legacy_baseline",
    )
    parser.add_argument("--per-label", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "evaluation" / "inference_verification.json",
    )
    args = parser.parse_args()

    gold_rows = select_gold(load_jsonl(args.gold), args.per_label)
    if len(gold_rows) < 10:
        raise ValueError("Frozen gold selection must contain at least 10 rows")

    config = TransformerClassifierConfig(
        model_path=args.transformer_model,
        model_name="transformer_sentiment_v2_weighted",
        max_length=192,
    )
    deployment_transformer = TransformerSentimentClassifier(config)
    legacy = SentimentClassifier(args.legacy_artifacts)
    texts = [str(row["text"]) for row in gold_rows]

    offline = direct_predictions(deployment_transformer, texts)
    deployed = deployment_transformer.predict_many(texts)
    legacy_outputs = legacy.predict_many(texts)
    cases = []
    for row, offline_row, deployed_row, legacy_row in zip(
        gold_rows, offline, deployed, legacy_outputs
    ):
        cases.append(
            {
                "sample_id": str(row.get("sample_id", "")),
                "text": row["text"],
                "gold": row["label"],
                "offline_transformer": offline_row["label"],
                "deployment_transformer": deployed_row.label,
                "current_modelscope_legacy": legacy_row.label,
                "raw_label_id": offline_row["label_id"],
                "transformer_probabilities": offline_row["probabilities"],
            }
        )

    available_labels = sorted({str(row["label"]) for row in load_jsonl(args.gold)})
    missing_labels = sorted(set(EXPECTED_ID2LABEL.values()) - set(available_labels))
    source_weight = args.transformer_model / "model.safetensors"
    report = {
        "gold_source": str(args.gold.resolve()),
        "selection_rule": f"first {args.per_label} rows per available label; not selected by correctness",
        "available_gold_labels": available_labels,
        "missing_gold_labels": missing_labels,
        "sample_count": len(cases),
        "model_source": str(args.transformer_model.resolve()),
        "model_weight_bytes": source_weight.stat().st_size,
        "model_weight_sha256": sha256(source_weight),
        "id2label": {
            str(key): value
            for key, value in deployment_transformer._pipeline.model.config.id2label.items()
        },
        "max_length": config.max_length,
        "metrics_on_selected_rows": {
            "offline_transformer_accuracy": accuracy(cases, "offline_transformer"),
            "deployment_transformer_accuracy": accuracy(cases, "deployment_transformer"),
            "current_modelscope_legacy_accuracy": accuracy(cases, "current_modelscope_legacy"),
            "offline_deployment_agreement": sum(
                case["offline_transformer"] == case["deployment_transformer"]
                for case in cases
            )
            / len(cases),
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("gold\toffline\tdeployment\tcurrent_modelscope_legacy\ttext")
    for case in cases:
        print(
            f"{case['gold']}\t{case['offline_transformer']}\t"
            f"{case['deployment_transformer']}\t{case['current_modelscope_legacy']}\t"
            f"{case['text']}"
        )
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))

    if report["metrics_on_selected_rows"]["offline_deployment_agreement"] != 1.0:
        raise SystemExit("Offline and deployment Transformer chains still disagree")


if __name__ == "__main__":
    main()
