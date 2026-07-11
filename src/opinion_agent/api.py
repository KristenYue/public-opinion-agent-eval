"""FastAPI entrypoint with lazy model initialization."""

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
import os
import uuid

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from opinion_agent.agent.graph import build_opinion_graph
from opinion_agent.agent.reviewer import OpenAICompatibleReviewer
from opinion_agent.retrieval import HybridEventRetriever, SemanticEventRetriever, TfidfEventRetriever
from opinion_agent.sentiment import (
    SentimentClassifier,
    SnowNLPSentimentClassifier,
    TransformerClassifierConfig,
    TransformerSentimentClassifier,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
PRIVATE_EVENT_CARDS = PROJECT_ROOT / "data" / "processed" / "event_cards.jsonl"
DEMO_EVENT_CARDS = PROJECT_ROOT / "examples" / "demo_event_cards.jsonl"


class CommentInput(BaseModel):
    sample_id: str
    text: str = Field(min_length=1, max_length=5000)
    context: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=2000)


class AnalyzeRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2000)
    comments: list[CommentInput] = Field(min_length=1, max_length=500)


def create_app(graph_provider: Callable[[], object]) -> FastAPI:
    app = FastAPI(title="Opinion Analysis Agent", version="0.1.0")
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/console")

    @app.get("/console", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/analyze")
    async def analyze(request: AnalyzeRequest) -> dict[str, object]:
        graph = await run_in_threadpool(graph_provider)
        state = {
            "request_id": str(uuid.uuid4()),
            "event_id": request.event_id,
            "query": request.query,
            "comments": [comment.model_dump(exclude_none=True) for comment in request.comments],
            "tool_traces": [],
            "errors": [],
        }
        return await run_in_threadpool(graph.invoke, state)  # type: ignore[attr-defined, no-any-return]

    return app


@lru_cache(maxsize=1)
def get_default_graph():
    cards = resolve_event_cards_path()
    sparse = TfidfEventRetriever(cards)
    dense = SemanticEventRetriever(cards)
    retriever = HybridEventRetriever(sparse, dense, min_dense_score=0.55)
    reviewer = None
    if all(os.getenv(name) for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")):
        reviewer = OpenAICompatibleReviewer(
            base_url=os.environ["LLM_BASE_URL"],
            api_key=os.environ["LLM_API_KEY"],
            model=os.environ["LLM_MODEL"],
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            max_attempts=int(os.getenv("LLM_MAX_ATTEMPTS", "3")),
            max_input_chars=int(os.getenv("LLM_MAX_INPUT_CHARS", "50000")),
        )
    return build_opinion_graph(
        build_sentiment_classifier(),
        retriever,
        SnowNLPSentimentClassifier(),
        reviewer,
    )


def build_sentiment_classifier():
    backend = os.getenv("SENTIMENT_BACKEND", "legacy_xgboost").strip().lower()
    if backend in {"legacy_xgboost", "legacy", "xgboost"}:
        return SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
    if backend == "transformer":
        configured_path = os.getenv(
            "TRANSFORMER_MODEL_PATH",
            str(PROJECT_ROOT / "artifacts" / "transformer_sentiment_v1"),
        )
        model_path = resolve_project_path(configured_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Transformer model path does not exist: {model_path}. "
                "Train it with scripts/train_transformer_sentiment.py or set "
                "TRANSFORMER_MODEL_PATH to a Hugging Face-compatible model directory."
            )
        return TransformerSentimentClassifier(
            TransformerClassifierConfig(
                model_path=model_path,
                model_name=os.getenv("TRANSFORMER_MODEL_NAME", "transformer_sentiment_v1"),
            )
        )
    raise ValueError(
        "Unsupported SENTIMENT_BACKEND. Expected 'legacy_xgboost' or 'transformer'."
    )


def resolve_event_cards_path() -> Path:
    """Prefer an explicit/private corpus and fall back to synthetic public demo cards."""
    configured = os.getenv("EVENT_CARDS_PATH")
    if configured:
        return resolve_project_path(configured)
    return PRIVATE_EVENT_CARDS if PRIVATE_EVENT_CARDS.exists() else DEMO_EVENT_CARDS


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


app = create_app(get_default_graph)
