"""Local retrieval baseline with a replaceable vector backend."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from opinion_agent.agent.state import Evidence


@dataclass(frozen=True)
class EventDocument:
    event_id: str
    document: str
    source_url: str


class TfidfEventRetriever:
    """Character n-gram vector retrieval used as the auditable RAG baseline."""

    def __init__(self, event_cards_path: str | Path) -> None:
        self.documents = _load_documents(event_cards_path)
        if not self.documents:
            raise ValueError("No event documents were loaded")
        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)
        self.matrix = self.vectorizer.fit_transform(doc.document for doc in self.documents)

    def retrieve(self, query: str, top_k: int = 3, exclude_event_id: str | None = None) -> list[Evidence]:
        if not query.strip():
            return []
        query_vector = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self.matrix)[0]
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)

        evidence: list[Evidence] = []
        for index in ranked:
            document = self.documents[index]
            if exclude_event_id and document.event_id == exclude_event_id:
                continue
            evidence.append(
                {
                    "evidence_id": sha256(
                        f"{document.event_id}:{document.document}".encode("utf-8")
                    ).hexdigest()[:16],
                    "event_id": document.event_id,
                    "chunk_type": "event_card",
                    "text": document.document,
                    "source_url": document.source_url,
                    "score": float(scores[index]),
                }
            )
            if len(evidence) >= top_k:
                break
        return evidence


class SemanticEventRetriever:
    """Dense semantic retrieval over event cards using a local embedding model."""

    def __init__(
        self,
        event_cards_path: str | Path,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        model: object | None = None,
        min_score: float | None = None,
    ) -> None:
        self.documents = _load_documents(event_cards_path)
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name)
        self.model = model
        self.model_name = model_name
        self.min_score = min_score
        self.matrix = np.asarray(
            self.model.encode(  # type: ignore[attr-defined]
                [document.document for document in self.documents],
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=float,
        )

    def retrieve(self, query: str, top_k: int = 3, exclude_event_id: str | None = None) -> list[Evidence]:
        if not query.strip():
            return []
        query_vector = np.asarray(
            self.model.encode(  # type: ignore[attr-defined]
                [query],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0],
            dtype=float,
        )
        scores = self.matrix @ query_vector
        ranked = np.argsort(scores)[::-1]

        evidence: list[Evidence] = []
        for index_value in ranked:
            index = int(index_value)
            document = self.documents[index]
            if exclude_event_id and document.event_id == exclude_event_id:
                continue
            if self.min_score is not None and float(scores[index]) < self.min_score:
                continue
            evidence.append(_to_evidence(document, float(scores[index])))
            if len(evidence) >= top_k:
                break
        return evidence


class HybridEventRetriever:
    """Fuse sparse and dense rankings with reciprocal-rank fusion."""

    def __init__(
        self,
        sparse: TfidfEventRetriever,
        dense: SemanticEventRetriever,
        rrf_k: int = 60,
        min_dense_score: float | None = 0.55,
    ) -> None:
        self.sparse = sparse
        self.dense = dense
        self.rrf_k = rrf_k
        self.min_dense_score = min_dense_score
        self.documents = sparse.documents

    def retrieve(self, query: str, top_k: int = 3, exclude_event_id: str | None = None) -> list[Evidence]:
        limit = len(self.documents)
        sparse_results = self.sparse.retrieve(query, top_k=limit, exclude_event_id=exclude_event_id)
        dense_results = self.dense.retrieve(query, top_k=limit, exclude_event_id=exclude_event_id)
        dense_scores = {item["evidence_id"]: item["score"] for item in dense_results}
        fused: dict[str, tuple[Evidence, float]] = {}
        for results in (sparse_results, dense_results):
            for rank, item in enumerate(results, start=1):
                score = 1.0 / (self.rrf_k + rank)
                current = fused.get(item["evidence_id"])
                fused[item["evidence_id"]] = (item, score + (current[1] if current else 0.0))
        ranked = sorted(fused.values(), key=lambda pair: pair[1], reverse=True)
        accepted = [
            (item, score)
            for item, score in ranked
            if self.min_dense_score is None
            or dense_scores.get(item["evidence_id"], float("-inf")) >= self.min_dense_score
        ]
        return [{**item, "score": score} for item, score in accepted[:top_k]]


def _first_source_url(card: dict[str, object]) -> str:
    posts = card.get("representative_posts", [])
    if isinstance(posts, list) and posts and isinstance(posts[0], dict):
        return str(posts[0].get("source_url", ""))
    return ""


def _load_documents(event_cards_path: str | Path) -> list[EventDocument]:
    path = Path(event_cards_path)
    # splitlines() also splits valid Unicode separators such as U+2028 that
    # may occur inside social-media text, corrupting otherwise valid JSONL.
    cards = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    documents = [
        EventDocument(
            event_id=str(card["event_id"]),
            document=str(card["document"]),
            source_url=_first_source_url(card),
        )
        for card in cards
        if str(card.get("document", "")).strip()
    ]
    if not documents:
        raise ValueError("No event documents were loaded")
    return documents


def _to_evidence(document: EventDocument, score: float) -> Evidence:
    return {
        "evidence_id": sha256(
            f"{document.event_id}:{document.document}".encode("utf-8")
        ).hexdigest()[:16],
        "event_id": document.event_id,
        "chunk_type": "event_card",
        "text": document.document,
        "source_url": document.source_url,
        "score": score,
    }
