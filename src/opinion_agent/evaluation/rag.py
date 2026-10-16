"""Deterministic RAG retrieval and contamination evaluation."""

from __future__ import annotations

from hashlib import sha256
from math import log2
from pathlib import Path
from typing import Any
import json


def file_sha256(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def load_rag_evaluation(path: str | Path) -> dict[str, Any]:
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    queries = dataset.get("queries")
    gates = dataset.get("gates")
    if not isinstance(queries, list) or not queries:
        raise ValueError("RAG evaluation requires a non-empty queries list")
    if not isinstance(gates, dict) or not gates:
        raise ValueError("RAG evaluation requires metric gates")
    query_ids = [str(item.get("id", "")) for item in queries]
    if any(not item for item in query_ids) or len(query_ids) != len(set(query_ids)):
        raise ValueError("RAG query ids must be non-empty and unique")
    allowed = {"positive", "irrelevant", "prompt_injection"}
    unknown = sorted({str(item.get("category")) for item in queries} - allowed)
    if unknown:
        raise ValueError(f"unknown RAG query categories: {unknown}")
    return dataset


def evaluate_rag(retriever: Any, dataset: dict[str, Any], top_k: int = 5) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    positive_count = 0
    recall_sum = 0.0
    reciprocal_rank_sum = 0.0
    ndcg_sum = 0.0
    top1_correct = 0
    positive_with_evidence = 0
    irrelevant_count = 0
    irrelevant_rejected = 0
    injection_count = 0
    injection_rejected = 0
    bad_cases: list[dict[str, object]] = []

    for case in dataset["queries"]:
        results = retriever.retrieve(str(case["query"]), top_k=top_k)
        ranked = [str(item["event_id"]) for item in results]
        category = str(case["category"])
        relevant = {str(item) for item in case.get("relevant_event_ids", [])}

        if category == "positive":
            positive_count += 1
            positive_with_evidence += bool(ranked)
            hits = [index + 1 for index, event_id in enumerate(ranked) if event_id in relevant]
            recall = len({event_id for event_id in ranked if event_id in relevant}) / len(relevant)
            recall_sum += recall
            reciprocal_rank_sum += 1 / hits[0] if hits else 0.0
            dcg = sum(1 / log2(rank + 1) for rank in hits)
            ideal_hits = min(len(relevant), top_k)
            ideal_dcg = sum(1 / log2(rank + 1) for rank in range(1, ideal_hits + 1))
            ndcg_sum += dcg / ideal_dcg if ideal_dcg else 0.0
            top1_correct += bool(ranked and ranked[0] in relevant)
            if recall < 1.0 or not ranked or ranked[0] not in relevant:
                bad_cases.append(
                    {
                        "query_id": case["id"],
                        "category": category,
                        "expected": sorted(relevant),
                        "ranked": ranked,
                    }
                )
        elif category == "irrelevant":
            irrelevant_count += 1
            irrelevant_rejected += not ranked
            if ranked:
                bad_cases.append(
                    {
                        "query_id": case["id"],
                        "category": category,
                        "expected": [],
                        "ranked": ranked,
                    }
                )
        else:
            injection_count += 1
            prohibited = {str(item) for item in case.get("prohibited_event_ids", [])}
            rejected_ids = {
                str(item.get("event_id"))
                for item in getattr(retriever, "last_rejections", [])
            }
            passed = not prohibited.intersection(ranked) and prohibited <= rejected_ids
            injection_rejected += passed
            if not passed:
                bad_cases.append(
                    {
                        "query_id": case["id"],
                        "category": category,
                        "prohibited": sorted(prohibited),
                        "ranked": ranked,
                        "guard_rejected": sorted(rejected_ids),
                    }
                )

    metrics = {
        "recall_at_5": _ratio(recall_sum, positive_count),
        "mrr_at_5": _ratio(reciprocal_rank_sum, positive_count),
        "ndcg_at_5": _ratio(ndcg_sum, positive_count),
        "top1_citation_accuracy": _ratio(top1_correct, positive_count),
        "irrelevant_rejection_rate": _ratio(irrelevant_rejected, irrelevant_count),
        "prompt_injection_rejection_rate": _ratio(injection_rejected, injection_count),
        "positive_evidence_rate": _ratio(positive_with_evidence, positive_count),
    }
    gates = {str(key): float(value) for key, value in dataset["gates"].items()}
    gate_results = {
        name: {"actual": metrics.get(name), "minimum": minimum, "passed": metrics.get(name, 0) >= minimum}
        for name, minimum in gates.items()
    }
    return {
        "schema_version": dataset.get("schema_version"),
        "status": "passed" if all(item["passed"] for item in gate_results.values()) else "failed",
        "query_counts": {
            "positive": positive_count,
            "irrelevant": irrelevant_count,
            "prompt_injection": injection_count,
        },
        "metrics": metrics,
        "gates": gate_results,
        "bad_cases": bad_cases,
    }


def _ratio(numerator: float, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0
