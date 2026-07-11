from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np

from opinion_agent.retrieval import (  # noqa: E402
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)


class FakeEmbeddingModel:
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        vectors = []
        for text in texts:
            if "高温" in text:
                vectors.append([1.0, 0.0])
            elif "暴雨" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.5, 0.5])
        values = np.asarray(vectors, dtype=float)
        if normalize_embeddings:
            values /= np.linalg.norm(values, axis=1, keepdims=True)
        return values


def test_retriever_excludes_current_event(tmp_path: Path) -> None:
    cards = [
        {"event_id": "高温", "document": "高温天气持续，多地气温升高", "representative_posts": []},
        {"event_id": "暴雨", "document": "暴雨导致积水和交通拥堵", "representative_posts": []},
    ]
    path = tmp_path / "cards.jsonl"
    path.write_text("\n".join(json.dumps(card, ensure_ascii=False) for card in cards), encoding="utf-8")
    retriever = TfidfEventRetriever(path)

    result = retriever.retrieve("高温天气", top_k=1, exclude_event_id="高温")

    assert result[0]["event_id"] == "暴雨"


def test_retriever_keeps_unicode_line_separator_inside_json(tmp_path: Path) -> None:
    card = {
        "event_id": "事件A",
        "document": "第一段\u2028第二段",
        "representative_posts": [],
    }
    path = tmp_path / "cards.jsonl"
    path.write_text(json.dumps(card, ensure_ascii=False) + "\n", encoding="utf-8")

    retriever = TfidfEventRetriever(path)

    assert retriever.documents[0].document == "第一段\u2028第二段"


def test_semantic_retriever_uses_dense_similarity(tmp_path: Path) -> None:
    cards = [
        {"event_id": "高温", "document": "高温天气", "representative_posts": []},
        {"event_id": "暴雨", "document": "暴雨积水", "representative_posts": []},
    ]
    path = tmp_path / "cards.jsonl"
    path.write_text("\n".join(json.dumps(card, ensure_ascii=False) for card in cards), encoding="utf-8")

    retriever = SemanticEventRetriever(path, model=FakeEmbeddingModel())

    assert retriever.retrieve("高温预警", top_k=1)[0]["event_id"] == "高温"


def test_hybrid_retriever_fuses_both_rankings(tmp_path: Path) -> None:
    cards = [
        {"event_id": "高温", "document": "高温天气", "representative_posts": []},
        {"event_id": "暴雨", "document": "暴雨积水", "representative_posts": []},
    ]
    path = tmp_path / "cards.jsonl"
    path.write_text("\n".join(json.dumps(card, ensure_ascii=False) for card in cards), encoding="utf-8")
    sparse = TfidfEventRetriever(path)
    dense = SemanticEventRetriever(path, model=FakeEmbeddingModel())
    hybrid = HybridEventRetriever(sparse, dense, min_dense_score=0.5)

    result = hybrid.retrieve("高温天气", top_k=1)

    assert result[0]["event_id"] == "高温"
