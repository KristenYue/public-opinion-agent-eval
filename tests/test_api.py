from pathlib import Path
import sys

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent import api as api_module  # noqa: E402
from opinion_agent.api import (  # noqa: E402
    build_sentiment_classifier,
    create_app,
    resolve_event_cards_path,
)
from opinion_agent.retrieval import TfidfEventRetriever  # noqa: E402


class FakeGraph:
    def invoke(self, state):
        return {**state, "final_report": "ok"}


def test_sentiment_backend_rejects_unknown_value(monkeypatch) -> None:
    monkeypatch.setenv("SENTIMENT_BACKEND", "unknown")

    try:
        build_sentiment_classifier()
    except ValueError as exc:
        assert "SENTIMENT_BACKEND" in str(exc)
    else:
        raise AssertionError("Expected unsupported backend to fail")


def test_transformer_backend_uses_configured_model_path(monkeypatch, tmp_path) -> None:
    class FakeTransformerClassifier:
        def __init__(self, config):
            self.config = config

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    monkeypatch.setenv("SENTIMENT_BACKEND", "transformer")
    monkeypatch.setenv("TRANSFORMER_MODEL_PATH", str(model_dir))
    monkeypatch.setenv("TRANSFORMER_MODEL_NAME", "candidate_transformer")
    monkeypatch.setattr(api_module, "TransformerSentimentClassifier", FakeTransformerClassifier)

    classifier = build_sentiment_classifier()

    assert classifier.config.model_path == model_dir
    assert classifier.config.model_name == "candidate_transformer"


def test_analyze_endpoint_validates_and_invokes_graph() -> None:
    client = TestClient(create_app(lambda: FakeGraph()))
    response = client.post(
        "/v1/analyze",
        json={
            "event_id": "事件A",
            "query": "分析事件",
            "comments": [{"sample_id": "1", "text": "评论"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["final_report"] == "ok"


def test_console_and_static_assets_are_served() -> None:
    client = TestClient(create_app(lambda: FakeGraph()))

    console = client.get("/console")
    styles = client.get("/assets/styles.css")
    app_js = client.get("/assets/app.js")

    assert console.status_code == 200
    assert "舆情研判 Agent" in console.text
    assert 'id="review-warning"' in console.text
    assert styles.status_code == 200
    assert "--accent" in styles.text
    assert ".review-warning" in styles.text
    assert app_js.status_code == 200
    assert "尚未完成 LLM 或人工复核" in app_js.text


def test_public_demo_event_cards_can_bootstrap_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("EVENT_CARDS_PATH", "examples/demo_event_cards.jsonl")

    cards = resolve_event_cards_path()
    retriever = TfidfEventRetriever(cards)
    evidence = retriever.retrieve("进口商品成本和价格变化", top_k=1)

    assert cards == PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"
    assert evidence[0]["event_id"] == "示例-进口商品成本变化"
    assert evidence[0]["source_url"].startswith("https://example.com/synthetic/")
