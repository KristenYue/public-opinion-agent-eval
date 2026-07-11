"""Typed shared state for the opinion analysis agent."""

from operator import add
from typing import Annotated, Literal, NotRequired, TypedDict


SentimentLabel = Literal["Positive", "Neutral", "Negative", "Unscorable"]


class SentimentResult(TypedDict):
    sample_id: str
    text: str
    label: SentimentLabel
    confidence: float
    probabilities: dict[str, float]
    source: str
    secondary_label: NotRequired[SentimentLabel]
    secondary_score: NotRequired[float]
    models_agree: NotRequired[bool]


class AggregateStats(TypedDict):
    total: int
    scorable: int
    unscorable: int
    counts: dict[str, int]
    proportions: dict[str, float]
    model_disagreement_count: int
    model_disagreement_rate: float


class Evidence(TypedDict):
    evidence_id: str
    event_id: str
    chunk_type: Literal["event_card", "comment"]
    text: str
    source_url: str
    score: float


class RouteDecision(TypedDict):
    needs_review: bool
    reasons: list[str]
    policy_version: str


class ReviewItem(TypedDict):
    sample_id: str
    label: SentimentLabel
    rationale: str
    confidence: Literal["High", "Medium", "Low"]
    applied: NotRequired[bool]
    final_label: NotRequired[SentimentLabel]
    decision_reason: NotRequired[str]


class ReviewResult(TypedDict):
    items: list[ReviewItem]
    summary: str
    reviewer: str
    usage: NotRequired[dict[str, int]]
    attempts: NotRequired[int]
    idempotency_key: NotRequired[str]


class RiskAssessment(TypedDict):
    attention_level: Literal["Low", "Medium", "High", "Uncertain"]
    factors: list[str]
    limitations: list[str]


class OpinionBrief(TypedDict):
    event_id: str
    executive_summary: str
    attention_level: Literal["Low", "Medium", "High", "Uncertain"]
    sentiment_snapshot: dict[str, object]
    risk_signals: list[str]
    disputed_sample_ids: list[str]
    evidence_references: list[dict[str, object]]
    review_status: Literal[
        "not_required", "manual_required", "llm_completed", "llm_failed"
    ]
    recommended_actions: list[str]
    limitations: list[str]


class TraceEvent(TypedDict):
    node: str
    status: Literal["ok", "error", "degraded"]
    duration_ms: float
    details: dict[str, object]


class ErrorInfo(TypedDict):
    node: str
    error_type: str
    message: str
    recoverable: bool


class AgentState(TypedDict):
    request_id: str
    event_id: str
    query: str
    comments: list[dict[str, str]]
    sentiment_results: NotRequired[list[SentimentResult]]
    aggregate_stats: NotRequired[AggregateStats]
    retrieved_evidence: NotRequired[list[Evidence]]
    route_decision: NotRequired[RouteDecision]
    review_result: NotRequired[ReviewResult | None]
    risk_assessment: NotRequired[RiskAssessment | None]
    analysis_report: NotRequired[OpinionBrief]
    final_report: NotRequired[str | None]
    tool_traces: Annotated[list[TraceEvent], add]
    errors: Annotated[list[ErrorInfo], add]
