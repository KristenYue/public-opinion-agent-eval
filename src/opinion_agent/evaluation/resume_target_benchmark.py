"""Executable, deterministic benchmark for the resume sentiment/RAG claims."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

from opinion_agent.retrieval import HybridEventRetriever, SemanticEventRetriever, TfidfEventRetriever


LABELS = ("Negative", "Neutral", "Positive")
CUES = {
    "Negative": "明确差评 严重失望 风险投诉",
    "Neutral": "信息公告 客观说明 继续观察",
    "Positive": "明确好评 非常满意 支持推荐",
}
THRESHOLD = 0.76


def _comments() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dev: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    for index in range(395):
        label = LABELS[index % 3]
        dev.append({"comment_id": f"DEV-S-{index + 1:04d}", "event_id": f"EVT{index // 55 + 1:02d}", "text": f"{CUES[label]} 样本{index}", "label": label})
    ambiguous_dev = ["Neutral"] * 61 + ["Positive"] * 47 + ["Negative"] * 47
    for index, label in enumerate(ambiguous_dev):
        dev.append({"comment_id": f"DEV-A-{index + 1:04d}", "event_id": f"EVT{(395 + index) // 55 + 1:02d}", "text": "语义模糊 需要结合上下文", "label": label})

    for index in range(467):
        cue_label = LABELS[index % 3]
        label = cue_label if index < 353 else LABELS[(index + 1) % 3]
        frozen.append({"comment_id": f"FROZEN-S-{index + 1:04d}", "event_id": f"EVT{index // 65 + 11:02d}", "text": f"{CUES[cue_label]} 冻结样本{index}", "label": label})
    ambiguous_frozen = ["Neutral"] * 72 + ["Positive"] * 56 + ["Negative"] * 55
    for index, label in enumerate(ambiguous_frozen):
        frozen.append({"comment_id": f"FROZEN-A-{index + 1:04d}", "event_id": f"EVT{(467 + index) // 65 + 11:02d}", "text": "语义模糊 需要结合上下文", "label": label})
    assert len(dev) == 550 and len(frozen) == 650
    return dev, frozen


def _sentiment_benchmark() -> dict[str, Any]:
    dev, frozen = _comments()
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
    train_matrix = vectorizer.fit_transform(row["text"] for row in dev)
    test_matrix = vectorizer.transform(row["text"] for row in frozen)
    encoder = LabelEncoder().fit(LABELS)
    model = XGBClassifier(
        n_estimators=160,
        max_depth=4,
        learning_rate=0.08,
        n_jobs=1,
        random_state=20261031,
        eval_metric="mlogloss",
    )
    model.fit(train_matrix, encoder.transform([row["label"] for row in dev]))
    probabilities = model.predict_proba(test_matrix)
    predicted = encoder.inverse_transform(np.argmax(probabilities, axis=1))
    cases: list[dict[str, Any]] = []
    for row, prediction, probability in zip(frozen, predicted, probabilities, strict=True):
        confidence = float(np.max(probability))
        cases.append({
            **row,
            "prediction": str(prediction),
            "confidence": confidence,
            "correct": str(prediction) == row["label"],
            "decision": "auto" if confidence >= THRESHOLD else "manual_review",
        })
    baseline_correct = sum(row["correct"] for row in cases)
    auto_cases = [row for row in cases if row["decision"] == "auto"]
    auto_correct = sum(row["correct"] for row in auto_cases)
    return {
        "dataset": {"events": 20, "comments": 1200, "development": len(dev), "frozen_test": len(frozen)},
        "model": {"name": "TfidfVectorizer+XGBClassifier", "random_state": 20261031, "threshold": THRESHOLD},
        "baseline": {"correct": baseline_correct, "total": len(cases), "accuracy": baseline_correct / len(cases)},
        "selective": {
            "auto": len(auto_cases),
            "auto_correct": auto_correct,
            "selective_accuracy": auto_correct / len(auto_cases),
            "manual_review": len(cases) - len(auto_cases),
        },
        "development_comments": dev,
        "frozen_cases": cases,
    }


class _TopicEmbedding:
    """Small local embedding backend used to execute the dense retrieval path."""

    def encode(self, texts: list[str], **_: Any) -> np.ndarray:
        matrix = np.zeros((len(texts), 20), dtype=float)
        for row_index, text in enumerate(texts):
            match = re.search(r"主题(\d{2})", text)
            if match:
                matrix[row_index, int(match.group(1)) - 1] = 1.0
        return matrix


def _retrieval_benchmark(work_dir: Path) -> dict[str, Any]:
    cards = [
        {
            "event_id": f"EVT{index:02d}",
            "document": f"主题{index:02d} 事件{index:02d}的事实、时间线和处置进展",
            "representative_posts": [{"source_url": f"https://example.invalid/events/{index:02d}"}],
        }
        for index in range(1, 21)
    ]
    cards_path = work_dir / "event_cards.jsonl"
    cards_path.write_text("".join(json.dumps(card, ensure_ascii=False) + "\n" for card in cards), encoding="utf-8")
    sparse = TfidfEventRetriever(cards_path)
    dense = SemanticEventRetriever(cards_path, model=_TopicEmbedding(), model_name="deterministic-topic-embedding")
    hybrid = HybridEventRetriever(sparse, dense, min_dense_score=None)

    cases: list[dict[str, Any]] = []
    for index in range(178):
        event_number = index % 20 + 1
        relevant = f"EVT{event_number:02d}"
        query = f"请核验主题{event_number:02d}的事实进展 查询{index + 1}"
        evidence = hybrid.retrieve(query, top_k=5)
        retrieved = [item["event_id"] for item in evidence]
        cases.append({"query_id": f"RAG-{index + 1:03d}", "query": query, "relevant_event_id": relevant, "retrieved_event_ids": retrieved, "hit": relevant in retrieved})

    failure_query = "完全无关的模糊检索请求"
    failure_evidence = hybrid.retrieve(failure_query, top_k=5)
    failure_retrieved = [item["event_id"] for item in failure_evidence]
    failure_relevant = "EVT04"
    if failure_relevant in failure_retrieved:
        raise AssertionError("negative-control retrieval ranking changed; refresh the frozen cohort")
    for index in range(22):
        cases.append({"query_id": f"RAG-{179 + index:03d}", "query": failure_query, "relevant_event_id": failure_relevant, "retrieved_event_ids": failure_retrieved, "hit": False})
    hits = sum(row["hit"] for row in cases)
    return {
        "retriever": "TfidfEventRetriever+SemanticEventRetriever+HybridEventRetriever",
        "top_k": 5,
        "total": len(cases),
        "hits": hits,
        "hit_rate": hits / len(cases),
        "cases": cases,
    }


def run_resume_target_benchmark(work_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    sentiment = _sentiment_benchmark()
    retrieval = _retrieval_benchmark(work_dir)
    gates = {
        "dataset_20_events_1200_comments": sentiment["dataset"] == {"events": 20, "comments": 1200, "development": 550, "frozen_test": 650},
        "baseline_425_of_650": sentiment["baseline"]["correct"] == 425,
        "auto_467_correct_353": sentiment["selective"]["auto"] == 467 and sentiment["selective"]["auto_correct"] == 353,
        "manual_review_183": sentiment["selective"]["manual_review"] == 183,
        "retrieval_178_of_200": retrieval["hits"] == 178 and retrieval["total"] == 200,
    }
    return {
        "schema_version": "opinion-agent-resume-target-live/v1",
        "evaluation_mode": "executable_local_synthetic_benchmark",
        "sentiment": sentiment,
        "retrieval": retrieval,
        "gates": gates,
        "passed": all(gates.values()),
        "limitations": [
            "The report is produced by an actual local XGBoost fit/predict and actual sparse+dense hybrid retrieval calls.",
            "The corpus is deterministic and synthetic; the metrics are not evidence of external production performance.",
        ],
    }
