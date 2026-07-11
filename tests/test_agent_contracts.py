from copy import deepcopy
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent.agent.graph import build_opinion_graph  # noqa: E402
from opinion_agent.evaluation.agent_contracts import evaluate_agent_contract  # noqa: E402
from opinion_agent.sentiment.classifier import Prediction  # noqa: E402
from opinion_agent.sentiment.snownlp_baseline import SecondaryPrediction  # noqa: E402


class StubClassifier:
    def predict(self, text: str) -> Prediction:
        return Prediction("Positive", 0.8, {"Positive": 0.8}, text)


class AgreeingSecondaryClassifier:
    def predict(self, text: str) -> SecondaryPrediction:
        return SecondaryPrediction("Positive", 0.8)


class StubRetriever:
    def retrieve(self, query: str, top_k: int, exclude_event_id: str):
        return [
            {
                "evidence_id": "evidence-1",
                "event_id": "historical-event",
                "chunk_type": "event_card",
                "text": "历史事件及处置摘要",
                "source_url": "https://example.com/history",
                "score": 0.82,
            }
        ]


def _run_graph() -> tuple[dict[str, object], dict[str, object]]:
    request: dict[str, object] = {
        "request_id": "contract-1",
        "event_id": "current-event",
        "query": "分析当前事件",
        "comments": [{"sample_id": "sample-1", "text": "整体反馈保持积极稳定"}],
        "tool_traces": [],
        "errors": [],
    }
    graph = build_opinion_graph(
        StubClassifier(),  # type: ignore[arg-type]
        StubRetriever(),  # type: ignore[arg-type]
        AgreeingSecondaryClassifier(),  # type: ignore[arg-type]
    )
    return request, graph.invoke(request)


def test_agent_contract_accepts_grounded_baseline_run() -> None:
    request, result = _run_graph()

    evaluation = evaluate_agent_contract(request, result)

    assert evaluation["passed"] is True
    assert evaluation["checks_passed"] == evaluation["checks_total"] == 8
    assert evaluation["failed_checks"] == []


def test_agent_contract_exposes_provenance_and_status_mismatches() -> None:
    request, result = _run_graph()
    broken = deepcopy(result)
    broken["analysis_report"]["evidence_references"][0]["source_url"] = (
        "https://example.com/wrong"
    )
    broken["analysis_report"]["review_status"] = "manual_required"

    evaluation = evaluate_agent_contract(request, broken)

    assert evaluation["passed"] is False
    assert evaluation["failed_checks"] == [
        "evidence_provenance_integrity",
        "review_fallback_consistency",
    ]
