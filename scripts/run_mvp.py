"""Run the current local MVP without any external LLM API."""

from argparse import ArgumentParser
from pathlib import Path
import json
import sys
import uuid

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.retrieval import (  # noqa: E402
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)
from opinion_agent.sentiment import SentimentClassifier, SnowNLPSentimentClassifier  # noqa: E402


def main() -> None:
    parser = ArgumentParser(description="Run the opinion-agent MVP on one event")
    parser.add_argument("--event-id", default="关税")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--retriever", choices=["tfidf", "dense", "hybrid"], default="hybrid")
    args = parser.parse_args()

    comments = pd.read_csv(PROJECT_ROOT / "data" / "processed" / "comments_deduplicated.csv")
    selected = comments.loc[comments["event_id"] == args.event_id].head(args.limit)
    if selected.empty:
        raise SystemExit(f"Unknown event_id: {args.event_id}")

    classifier = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    cards = PROJECT_ROOT / "data" / "processed" / "event_cards.jsonl"
    sparse = TfidfEventRetriever(cards)
    if args.retriever == "tfidf":
        retriever = sparse
    else:
        dense = SemanticEventRetriever(cards)
        retriever = dense if args.retriever == "dense" else HybridEventRetriever(sparse, dense)
    graph = build_opinion_graph(classifier, retriever, SnowNLPSentimentClassifier())
    result = graph.invoke(
        {
            "request_id": str(uuid.uuid4()),
            "event_id": args.event_id,
            "query": f"分析{args.event_id}事件的评论情绪并检索历史相似事件",
            "comments": [
                {"sample_id": str(row.sample_id), "text": str(row.normalized_text)}
                for row in selected.itertuples()
            ],
            "tool_traces": [],
            "errors": [],
        }
    )
    compact = {
        "request_id": result["request_id"],
        "event_id": result["event_id"],
        "aggregate_stats": result["aggregate_stats"],
        "retrieved_evidence": [
            {
                "event_id": item["event_id"],
                "score": round(item["score"], 4),
                "source_url": item["source_url"],
            }
            for item in result["retrieved_evidence"]
        ],
        "route_decision": result["route_decision"],
        "final_report": result["final_report"],
        "tool_traces": result["tool_traces"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
