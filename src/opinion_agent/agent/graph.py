"""Construction of the executable LangGraph workflow."""

from langgraph.graph import END, START, StateGraph

from opinion_agent.sentiment import SentimentClassifier
from opinion_agent.sentiment.snownlp_baseline import SnowNLPSentimentClassifier
from opinion_agent.retrieval import HybridEventRetriever, SemanticEventRetriever, TfidfEventRetriever

from .nodes import (
    build_evidence_retriever_node,
    build_llm_review_node,
    build_sentiment_classifier_node,
    mark_baseline_ready,
    mark_review_required,
    run_briefing_composer,
    run_sentiment_aggregator,
    run_review_router,
)
from .state import AgentState
from .nodes import Reviewer


def build_opinion_graph(
    classifier: SentimentClassifier,
    retriever: TfidfEventRetriever | SemanticEventRetriever | HybridEventRetriever | None = None,
    secondary_classifier: SnowNLPSentimentClassifier | None = None,
    reviewer: Reviewer | None = None,
):
    """Build the first end-to-end slice of the opinion analysis workflow."""
    builder = StateGraph(AgentState)
    builder.add_node(
        "sentiment_classifier",
        build_sentiment_classifier_node(classifier, secondary_classifier),
    )
    builder.add_node("sentiment_aggregator", run_sentiment_aggregator)
    builder.add_node("briefing_composer", run_briefing_composer)
    builder.add_edge(START, "sentiment_classifier")
    builder.add_edge("sentiment_classifier", "sentiment_aggregator")
    if retriever is None:
        builder.add_edge("sentiment_aggregator", "briefing_composer")
    else:
        builder.add_node("evidence_retriever", build_evidence_retriever_node(retriever))
        builder.add_node("review_router", run_review_router)
        review_node = build_llm_review_node(reviewer) if reviewer else mark_review_required
        builder.add_node("review_required", review_node)
        builder.add_node("baseline_ready", mark_baseline_ready)
        builder.add_edge("sentiment_aggregator", "evidence_retriever")
        builder.add_edge("evidence_retriever", "review_router")
        builder.add_conditional_edges(
            "review_router",
            lambda state: "review_required" if state["route_decision"]["needs_review"] else "baseline_ready",
            {
                "review_required": "review_required",
                "baseline_ready": "baseline_ready",
            },
        )
        builder.add_edge("review_required", "briefing_composer")
        builder.add_edge("baseline_ready", "briefing_composer")
    builder.add_edge("briefing_composer", END)
    return builder.compile()
