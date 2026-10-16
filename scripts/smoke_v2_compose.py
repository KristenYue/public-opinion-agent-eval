"""Exercise the complete V2 Compose stack through its public HTTP surfaces.

This script intentionally uses only the Python standard library so the CI smoke
test does not need to install the application into the GitHub runner itself.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PROMETHEUS_BASE_URL = os.getenv(
    "PROMETHEUS_BASE_URL", "http://127.0.0.1:9090"
).rstrip("/")
GRAFANA_BASE_URL = os.getenv(
    "GRAFANA_BASE_URL", "http://127.0.0.1:3000"
).rstrip("/")
PROJECT_ID = os.getenv(
    "V2_PROJECT_ID", "11111111-1111-1111-1111-111111111111"
)
API_KEY = os.getenv("V2_API_KEY", "").strip()
TIMEOUT_SECONDS = float(os.getenv("COMPOSE_SMOKE_TIMEOUT_SECONDS", "240"))
POLL_SECONDS = float(os.getenv("COMPOSE_SMOKE_POLL_SECONDS", "2"))


def normalize_headers(items: Any) -> dict[str, str]:
    """Return HTTP response headers with RFC case-insensitive lookup semantics."""

    return {str(key).lower(): str(value) for key, value in items}


def request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=body, headers=request_headers, method=method)
    with urlopen(req, timeout=10) as response:  # noqa: S310 - fixed local CI URLs
        return (
            response.status,
            normalize_headers(response.headers.items()),
            response.read(),
        )


def json_request(url: str, **kwargs: Any) -> tuple[int, dict[str, str], Any]:
    status, headers, body = request(url, **kwargs)
    return status, headers, json.loads(body.decode("utf-8"))


def wait_until(label: str, check: Any, deadline: float) -> Any:
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (HTTPError, URLError, TimeoutError, ConnectionError, ValueError) as exc:
            last_error = exc
        time.sleep(POLL_SECONDS)
    detail = f": {type(last_error).__name__}: {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {label}{detail}")


def main() -> int:
    if not API_KEY:
        raise RuntimeError("V2_API_KEY is required for authenticated Compose smoke")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    auth_headers = {"X-API-Key": API_KEY}

    def api_ready() -> dict[str, Any] | None:
        status, _, payload = json_request(f"{API_BASE_URL}/ready")
        dependencies = payload.get("dependencies", {})
        if (
            status == 200
            and payload.get("status") == "ok"
            and payload.get("mode") == "v2"
            and dependencies.get("database") is True
            and dependencies.get("queue") is True
        ):
            return payload
        return None

    readiness = wait_until("V2 API readiness", api_ready, deadline)
    wait_until(
        "Prometheus readiness",
        lambda: request(f"{PROMETHEUS_BASE_URL}/-/ready")[0] == 200,
        deadline,
    )
    def grafana_ready() -> dict[str, Any] | None:
        status, _, payload = json_request(f"{GRAFANA_BASE_URL}/api/health")
        if status == 200 and payload.get("database") == "ok":
            return payload
        return None

    grafana = wait_until("Grafana health", grafana_ready, deadline)

    submission = {
        "project_id": PROJECT_ID,
        "requested_by": "untrusted-client-claim",
        "event_id": "compose-smoke-event",
        "query": "分析合成事件舆情并给出可审计结论",
        "comments": [
            {
                "sample_id": "compose-smoke-comment-1",
                "text": "政策信息已经发布，建议持续观察后续公开数据。",
            }
        ],
    }
    anonymous_status, _, _ = json_request(
        f"{API_BASE_URL}/v2/jobs",
        method="POST",
        payload=submission,
        headers={"Idempotency-Key": "compose-smoke-anonymous"},
    )
    if anonymous_status != 401:
        raise RuntimeError("V2 job submission must reject an absent API key")
    status, headers, job = json_request(
        f"{API_BASE_URL}/v2/jobs",
        method="POST",
        payload=submission,
        headers={**auth_headers, "Idempotency-Key": "compose-smoke-v1"},
    )
    replayed = headers.get("idempotency-replayed", "").lower()
    if status != 202 or replayed != "false":
        raise RuntimeError(
            "first V2 submission did not create a new job: "
            f"status={status}, idempotency_replayed={replayed!r}"
        )
    job_id = job["id"]
    if job.get("requested_by") != "compose-smoke":
        raise RuntimeError("server did not replace client requested_by with authenticated subject")

    def terminal_job() -> dict[str, Any] | None:
        job_status, _, current = json_request(
            f"{API_BASE_URL}/v2/jobs/{job_id}", headers=auth_headers
        )
        if job_status != 200:
            return None
        if current.get("status") in {"completed", "manual_required", "failed_closed"}:
            return current
        return None

    finished = wait_until("V2 job terminal state", terminal_job, deadline)
    if finished["status"] == "failed_closed":
        raise RuntimeError(
            "V2 job failed closed: "
            f"{finished.get('error_code')}: {finished.get('error_message')}"
        )

    replay_status, replay_headers, replay = json_request(
        f"{API_BASE_URL}/v2/jobs",
        method="POST",
        payload=submission,
        headers={**auth_headers, "Idempotency-Key": "compose-smoke-v1"},
    )
    if (
        replay_status != 202
        or replay["id"] != job_id
        or replay_headers.get("idempotency-replayed", "").lower() != "true"
    ):
        raise RuntimeError("idempotent replay did not return the original job")

    trace_status, _, trace = json_request(
        f"{API_BASE_URL}/v2/jobs/{job_id}/trace", headers=auth_headers
    )
    if trace_status != 200 or trace["job"]["id"] != job_id or not trace["runs"]:
        raise RuntimeError("durable trace is missing the completed run")
    run = trace["runs"][-1]
    checkpoint_kinds = [row["checkpoint_kind"] for row in run["checkpoints"]]
    if not checkpoint_kinds or checkpoint_kinds[0] != "input_replay":
        raise RuntimeError("trace does not begin with an input_replay checkpoint")
    if checkpoint_kinds[-1] != "completed":
        raise RuntimeError("trace does not end with a completed checkpoint")
    if run["status"] not in {"completed", "manual_required"}:
        raise RuntimeError(f"unexpected run status: {run['status']}")
    if trace["shadow_runs"]:
        raise RuntimeError("shadow runs must remain empty while the default flag is off")

    trace_page_status, _, trace_page = request(f"{API_BASE_URL}/trace")
    if trace_page_status != 200 or b'id="trace-form"' not in trace_page:
        raise RuntimeError("Trace viewer asset is not served by the image")
    metrics_status, _, metrics = request(f"{API_BASE_URL}/metrics")
    if metrics_status != 200 or b"opinion_agent_http_requests_total" not in metrics:
        raise RuntimeError("API Prometheus metrics are unavailable")

    summary = {
        "passed": True,
        "job_id": job_id,
        "job_status": finished["status"],
        "attempt_count": finished["attempt_count"],
        "checkpoint_kinds": checkpoint_kinds,
        "idempotent_replay": True,
        "anonymous_request_rejected": True,
        "shadow_default_off": True,
        "readiness": readiness,
        "grafana_database": grafana.get("database"),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"compose smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
