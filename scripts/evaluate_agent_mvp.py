"""Run the local Agent MVP over all event-level evaluation batches."""

from pathlib import Path
from collections import Counter
from statistics import median
from time import perf_counter
from argparse import ArgumentParser
import json
import math
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.evaluation.agent_contracts import evaluate_agent_contract  # noqa: E402
from opinion_agent.evaluation.baselines import normalize_prediction  # noqa: E402
from opinion_agent.retrieval import (  # noqa: E402
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


TASKS = PROJECT_ROOT / "data" / "evaluation" / "agent_eval_tasks.jsonl"
OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "agent_mvp_metrics.json"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)
    return ordered[index]


def main() -> None:
    parser = ArgumentParser(description="Evaluate one local Agent configuration")
    parser.add_argument("--retriever", choices=["tfidf", "hybrid"], default="hybrid")
    parser.add_argument("--tasks", type=Path, default=TASKS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    tasks = [
        json.loads(line)
        for line in args.tasks.read_text(encoding="utf-8").split("\n")
        if line
    ]
    cards = PROJECT_ROOT / "data" / "processed" / "event_cards.jsonl"
    sparse = TfidfEventRetriever(cards)
    if args.retriever == "tfidf":
        retriever = sparse
    else:
        dense = SemanticEventRetriever(cards)
        retriever = HybridEventRetriever(sparse, dense, min_dense_score=0.55)
    graph = build_opinion_graph(
        SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline"),
        retriever,
        SnowNLPSentimentClassifier(),
    )

    correct = 0
    total = 0
    execution_success = 0
    route_error_batches = 0
    captured_error_batches = 0
    correct_batches = 0
    false_review_batches = 0
    evidence_batches = 0
    briefing_reports = 0
    contract_successes = 0
    contract_check_passes: Counter[str] = Counter()
    review_status_counts: Counter[str] = Counter()
    attention_level_counts: Counter[str] = Counter()
    latencies: list[float] = []
    task_results: list[dict[str, object]] = []
    required_nodes = {
        "sentiment_classifier",
        "sentiment_aggregator",
        "evidence_retriever",
        "review_router",
        "briefing_composer",
    }

    for task in tasks:
        started = perf_counter()
        result = graph.invoke(
            {
                "request_id": task["task_id"],
                "event_id": task["event_id"],
                "query": task["query"],
                "comments": task["comments"],
                "tool_traces": [],
                "errors": [],
            }
        )
        elapsed_ms = (perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        expected = task["expected_labels"]
        predictions = {
            row["sample_id"]: normalize_prediction(row["label"])
            for row in result["sentiment_results"]
        }
        task_correct = sum(predictions[sample_id] == label for sample_id, label in expected.items())
        task_total = len(expected)
        correct += task_correct
        total += task_total
        has_error = task_correct < task_total
        needs_review = result["route_decision"]["needs_review"]
        if has_error:
            route_error_batches += 1
            captured_error_batches += int(needs_review)
        else:
            correct_batches += 1
            false_review_batches += int(needs_review)
        trace_nodes = {trace["node"] for trace in result["tool_traces"]}
        trace_sequence = [trace["node"] for trace in result["tool_traces"]]
        executed = required_nodes.issubset(trace_nodes) and not result.get("errors")
        execution_success += int(executed)
        evidence_batches += int(bool(result.get("retrieved_evidence")))
        briefing = result.get("analysis_report")
        briefing_reports += int(bool(briefing))
        if briefing:
            review_status_counts[str(briefing["review_status"])] += 1
            attention_level_counts[str(briefing["attention_level"])] += 1
        contract = evaluate_agent_contract(task, result)
        contract_successes += int(contract["passed"])
        for check_name, check in contract["checks"].items():
            contract_check_passes[check_name] += int(check["passed"])
        task_results.append(
            {
                "task_id": task["task_id"],
                "split": task["split"],
                "comments": task_total,
                "label_accuracy": task_correct / task_total,
                "has_label_error": has_error,
                "model_disagreement_rate": result["aggregate_stats"]["model_disagreement_rate"],
                "needs_review": needs_review,
                "review_reasons": result["route_decision"]["reasons"],
                "attention_level": result["analysis_report"]["attention_level"],
                "review_status": result["analysis_report"]["review_status"],
                "evidence_count": len(result.get("retrieved_evidence", [])),
                "execution_success": executed,
                "agent_contract_passed": contract["passed"],
                "failed_contract_checks": contract["failed_checks"],
                "trajectory": trace_sequence,
                "latency_ms": elapsed_ms,
            }
        )

    metrics = {
        "status": "partial_mvp_without_external_llm_reviewer",
        "configuration": {
            "retriever": args.retriever,
            "review_disagreement_threshold": os.getenv(
                "REVIEW_DISAGREEMENT_THRESHOLD", "0.0"
            ),
            "review_route_on_no_evidence": os.getenv("REVIEW_ROUTE_ON_NO_EVIDENCE", "1"),
        },
        "truth_status": (
            next(iter({str(task.get("truth_status", "unknown")) for task in tasks}))
            if len({str(task.get("truth_status", "unknown")) for task in tasks}) == 1
            else "mixed_partial_second_pass"
        ),
        "tasks": len(tasks),
        "comments": total,
        "tool_execution_success_rate": execution_success / len(tasks),
        "sentiment_accuracy": correct / total,
        "error_batch_review_recall": (
            captured_error_batches / route_error_batches if route_error_batches else 0.0
        ),
        "false_review_rate_on_fully_correct_batches": (
            false_review_batches / correct_batches if correct_batches else None
        ),
        "evidence_acceptance_rate": evidence_batches / len(tasks),
        "briefing_report_success_rate": briefing_reports / len(tasks),
        "agent_contract_success_rate": contract_successes / len(tasks),
        "agent_contract_check_rates": {
            check_name: passed / len(tasks)
            for check_name, passed in sorted(contract_check_passes.items())
        },
        "review_status_counts": dict(sorted(review_status_counts.items())),
        "attention_level_counts": dict(sorted(attention_level_counts.items())),
        "latency_ms": {
            "median": median(latencies),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies),
        },
        "limitations": [
            "No external LLM reviewer was called, so end-to-end corrected accuracy is not reported.",
            "Only part of the evaluation set has completed focused second-pass adjudication.",
            "Evidence acceptance is not evidence correctness; retrieval quality is evaluated separately.",
            "Agent contract success validates workflow consistency, not business conclusion correctness.",
        ],
        "task_results": task_results,
    }
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in metrics.items() if key != "task_results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
