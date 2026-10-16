"""FastAPI entrypoint with lazy model initialization."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
import asyncio
import logging
import os
from time import perf_counter
from typing import TYPE_CHECKING
import uuid

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse, Response as FastAPIResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from opinion_agent import __version__
from opinion_agent.agent.graph import build_opinion_graph
from opinion_agent.agent.reviewer import OfflineDemoReviewer, OpenAICompatibleReviewer
from opinion_agent.governance import (
    RequestBudgetExceeded,
    SecurityPolicy,
    SecurityPolicyError,
    redact_sensitive,
)
from opinion_agent.observability import HTTP_DURATION, HTTP_REQUESTS, log_event
from opinion_agent.retrieval import (
    GuardedRetriever,
    HybridEventRetriever,
    SemanticEventRetriever,
    TfidfEventRetriever,
)
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
DEFAULT_TRANSFORMER_MODEL = PROJECT_ROOT / "artifacts" / "transformer_sentiment_v2_weighted"
LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from opinion_agent.v2.jobs import JobService


class CommentInput(BaseModel):
    sample_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=5000)
    context: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=2000)


class AnalyzeRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=2000)
    comments: list[CommentInput] = Field(min_length=1, max_length=500)


def create_app(
    graph_provider: Callable[[], object],
    *,
    v2_job_service: "JobService | None" = None,
) -> FastAPI:
    security_policy = SecurityPolicy.from_env()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if v2_job_service is not None:
            close = getattr(v2_job_service.dispatcher, "close", None)
            if close is not None:
                await close()

    app = FastAPI(
        title="Opinion Analysis Agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.v2_job_service = v2_job_service
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")
    if v2_job_service is not None:
        from opinion_agent.v2.api import create_v2_router

        app.include_router(create_v2_router(v2_job_service))

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        started = perf_counter()
        request_id = request.headers.get("X-Request-ID", "").strip()[:128]
        request_id = request_id or uuid.uuid4().hex
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            route_object = request.scope.get("route")
            route = getattr(route_object, "path", "unmatched")
            duration = perf_counter() - started
            HTTP_REQUESTS.labels(request.method, route, str(status_code)).inc()
            HTTP_DURATION.labels(request.method, route).observe(duration)
            log_event(
                LOGGER,
                "http_request",
                request_id=request_id,
                method=request.method,
                route=route,
                status=status_code,
                duration_ms=round(duration * 1000, 3),
            )

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/console")

    @app.get("/console", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(STATIC_ROOT / "index.html")

    @app.get("/trace", include_in_schema=False)
    def trace_console() -> FileResponse:
        return FileResponse(STATIC_ROOT / "trace.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        if v2_job_service is None:
            return {"status": "ok", "mode": "v1", "dependencies": {}}
        try:
            dependencies = await asyncio.wait_for(
                v2_job_service.readiness(),
                timeout=float(os.getenv("READINESS_TIMEOUT_SECONDS", "3")),
            )
        except Exception as exc:
            LOGGER.warning("V2 readiness probe failed: %s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "reason": type(exc).__name__},
            ) from exc
        if not all(dependencies.values()):
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "dependencies": dependencies},
            )
        return {"status": "ok", "mode": "v2", "dependencies": dependencies}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> FastAPIResponse:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/analyze")
    async def analyze(request: AnalyzeRequest) -> dict[str, object]:
        raw_payload = request.model_dump(exclude_none=True)
        try:
            security_policy.validate_request_payload(raw_payload)
        except RequestBudgetExceeded as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        safe_payload = redact_sensitive(raw_payload)
        graph = await run_in_threadpool(graph_provider)
        state = {
            "request_id": str(uuid.uuid4()),
            "event_id": safe_payload["event_id"],
            "query": safe_payload["query"],
            "comments": safe_payload["comments"],
            "tool_traces": [],
            "errors": [],
        }
        result = redact_sensitive(
            await run_in_threadpool(graph.invoke, state)  # type: ignore[attr-defined, no-any-return]
        )
        try:
            security_policy.validate_result(result)
        except SecurityPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result

    return app


def build_v2_job_service():
    """Enable V2 only when both durable dependencies are explicitly configured."""

    database_url = os.getenv("DATABASE_URL", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not database_url and not redis_url:
        return None
    if not database_url or not redis_url:
        raise RuntimeError(
            "V2 requires DATABASE_URL and REDIS_URL together; partial configuration "
            "would accept jobs without a durable execution path"
        )

    from opinion_agent.v2.dispatcher import ArqJobDispatcher
    from opinion_agent.v2.jobs import JobService
    from opinion_agent.v2.repository import PsycopgJobRepository

    return JobService(
        PsycopgJobRepository(database_url),
        ArqJobDispatcher(
            redis_url,
            queue_name=os.getenv("ARQ_QUEUE_NAME", "opinion-agent"),
        ),
    )


@lru_cache(maxsize=1)
def get_default_graph():
    cards = resolve_event_cards_path()
    retriever = build_retriever(cards)
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
    elif os.getenv("ENABLE_OFFLINE_DEMO_REVIEWER", "0") == "1":
        reviewer = OfflineDemoReviewer()
    return build_opinion_graph(
        build_sentiment_classifier(),
        retriever,
        SnowNLPSentimentClassifier(),
        reviewer,
    )


def build_retriever(cards: str | Path):
    """Build hybrid retrieval, retaining an auditable sparse fallback."""
    threshold_text = os.getenv("RETRIEVAL_MIN_SCORE", "0.04").strip().lower()
    sparse_min_score = (
        None if threshold_text in {"", "none", "disabled"} else float(threshold_text)
    )
    sparse = TfidfEventRetriever(cards, min_score=sparse_min_score)
    if os.getenv("RETRIEVER_BACKEND", "hybrid").strip().lower() in {
        "tfidf",
        "sparse",
        "offline",
    }:
        sparse.runtime_backend = "tfidf_configured"
        sparse.fallback_reason = None
        return GuardedRetriever(sparse)
    try:
        dense = SemanticEventRetriever(cards)
        retriever = HybridEventRetriever(sparse, dense, min_dense_score=0.55)
        retriever.runtime_backend = "hybrid_bge_tfidf"
        retriever.fallback_reason = None
        return GuardedRetriever(retriever)
    except Exception as exc:
        sparse.runtime_backend = "tfidf_fallback"
        sparse.fallback_reason = f"{type(exc).__name__}: {str(exc)[:240]}"
        return GuardedRetriever(sparse)


def build_sentiment_classifier():
    # Keep the stronger verified legacy baseline as the public default. The
    # Transformer path is explicit until a frozen evaluation proves it better.
    backend = os.getenv("SENTIMENT_BACKEND", "legacy_xgboost").strip().lower()
    if backend in {"legacy_xgboost", "legacy", "xgboost"}:
        model = SentimentClassifier(PROJECT_ROOT / "artifacts" / "legacy_baseline")
        LOGGER.warning("Sentiment backend=legacy_xgboost path=%s", model.artifacts_dir)
        return model
    if backend == "transformer":
        configured_path = os.getenv(
            "TRANSFORMER_MODEL_PATH",
            str(DEFAULT_TRANSFORMER_MODEL),
        )
        model_path = resolve_project_path(configured_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Transformer model path does not exist: {model_path}. "
                "Train it with scripts/train_transformer_sentiment.py or set "
                "TRANSFORMER_MODEL_PATH to a Hugging Face-compatible model directory."
            )
        classifier = TransformerSentimentClassifier(
            TransformerClassifierConfig(
                model_path=model_path,
                model_name=os.getenv(
                    "TRANSFORMER_MODEL_NAME", "transformer_sentiment_v2_weighted"
                ),
                max_length=int(os.getenv("TRANSFORMER_MAX_LENGTH", "192")),
            )
        )
        LOGGER.warning(
            "Sentiment backend=transformer path=%s name=%s max_length=%s id2label=%s",
            model_path,
            classifier.config.model_name,
            classifier.config.max_length,
            getattr(classifier, "id2label", "validated by runtime classifier"),
        )
        return classifier
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


app = create_app(get_default_graph, v2_job_service=build_v2_job_service())
