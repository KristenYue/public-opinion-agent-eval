from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.sentiment.classifier import Prediction  # noqa: E402


class StubClassifier:
    def predict(self, text: str) -> Prediction:
        return Prediction("Positive", 0.75, {"Positive": 0.75}, text)


def test_graph_runs_sentiment_slice_end_to_end() -> None:
    graph = build_opinion_graph(StubClassifier())  # type: ignore[arg-type]
    result = graph.invoke(
        {
            "request_id": "request-1",
            "event_id": "event-1",
            "query": "生成事件分析",
            "comments": [{"sample_id": "sample-1", "text": "很好"}],
            "tool_traces": [],
            "errors": [],
        }
    )

    assert result["aggregate_stats"]["counts"] == {"Positive": 1}
    assert [trace["node"] for trace in result["tool_traces"]] == [
        "sentiment_classifier",
        "sentiment_aggregator",
        "briefing_composer",
    ]
    assert result["analysis_report"]["review_status"] == "not_required"
    assert result["analysis_report"]["attention_level"] == "Low"
