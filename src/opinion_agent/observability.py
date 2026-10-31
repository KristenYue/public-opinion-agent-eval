"""Low-cardinality operational metrics and structured event logging."""

from __future__ import annotations

import json
import logging
from typing import Any

from prometheus_client import Counter, Histogram


HTTP_REQUESTS = Counter(
    "opinion_agent_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "opinion_agent_http_request_duration_seconds",
    "API request latency in seconds.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
V2_JOB_SUBMISSIONS = Counter(
    "opinion_agent_v2_job_submissions_total",
    "V2 submission outcomes.",
    ("outcome",),
)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Write a JSON object without serializing credentials or request bodies."""

    logger.info(
        json.dumps(
            {"event": event, **fields},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    )
