# Production V2 Week 2: durable Job API

> 历史实现检查点：本文保留 Week 2 当时的范围与未完成项，不再作为当前 API 说明。当前契约、Trace API 和已验证恢复语义见 [V2_API.md](V2_API.md)，最终拓扑见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## What is implemented

- `POST /v2/jobs` returns `202 Accepted` after a durable PostgreSQL insert and
  successful Redis/ARQ enqueue.
- `GET /v2/jobs/{job_id}` returns the persisted lifecycle and safe result fields.
- `Idempotency-Key` is mandatory. Replaying the same normalized request returns
  the original job and does not enqueue it again.
- Reusing the same key for different content returns `409 Conflict`.
- If Redis enqueue fails after the database insert, the job becomes
  `failed_closed` with error code `queue_unavailable`, and the API returns 503.
- V2 routes are enabled only when both `DATABASE_URL` and `REDIS_URL` exist.
  V1 remains available without either dependency.

## Install and initialize

```powershell
python -m pip install -e ".[production]"
$env:DATABASE_URL="postgresql://opinion_agent:password@localhost:5432/opinion_agent"
$env:REDIS_URL="redis://localhost:6379/0"
python scripts/apply_v2_migrations.py
python -m uvicorn opinion_agent.api:app --host 127.0.0.1 --port 8000
# Run in a second process:
python -m arq opinion_agent.v2.arq_worker.WorkerSettings
```

The referenced `project_id` must already exist in `projects`. Project creation
and authorization are intentionally not invented inside job submission.

## Submit

```http
POST /v2/jobs
Idempotency-Key: demo-event-001
Content-Type: application/json

{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requested_by": "demo-user",
  "event_id": "event-001",
  "query": "分析该事件的风险",
  "comments": [
    {"sample_id": "c-1", "text": "这是一条待分析评论"}
  ]
}
```

The response header `Idempotency-Replayed` distinguishes the first accepted
submission (`false`) from a safe replay (`true`).

## Worker behavior

```mermaid
flowchart LR
    A[POST /v2/jobs] --> B[(PostgreSQL queued job)]
    B --> C[Redis / ARQ]
    C --> D{Atomic claim}
    D -->|already claimed| E[Stop without duplicate execution]
    D -->|claimed| F[Persist run + version snapshot]
    F --> G[Invoke existing Agent graph]
    G --> H[Persist traces, evidence, tokens, output]
    H --> I{Review status}
    I -->|resolved| J[completed]
    I -->|needs human| K[manual_required]
    G -->|transient uncaught error| L[retrying within budget]
    G -->|terminal / exhausted| M[failed_closed]
```

- A PostgreSQL compare-and-set update lets only a `queued` or `retrying` job be
  claimed, preventing duplicate workers from executing the same attempt.
- The run ledger and model/prompt/toolset/policy versions are written before the
  graph starts.
- Successful runs persist output state, evidence, node/tool traces, token totals
  and either `completed` or `manual_required`.
- Timeout, connection error, 429, 5xx and invalid JSON are retryable within the
  configured attempt budget. Exhausted or non-retryable failures close safely.
- Credentials and provider URLs are not written into version snapshots.

## Important boundary

The Worker implementation and unit-level failure policy are complete, but this
machine does not have Docker. A real PostgreSQL + Redis + ARQ integration run is
therefore still required before claiming verified end-to-end execution. Crash
recovery for jobs left in `running` also belongs to the next checkpoint slice.
