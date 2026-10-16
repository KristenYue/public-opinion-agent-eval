# Production V2 API

本文是 `production-v2` 的当前 API 契约。交互式 schema 在服务启动后访问 `/docs`；部署与环境变量见 [V2_DEPLOYMENT.md](V2_DEPLOYMENT.md)。

## 1. 启用条件与公共端点

同时配置 `DATABASE_URL` 和 `REDIS_URL` 时，应用注册 V2 路由。两者都未配置时只运行 V1；只配置其中一个会在启动时失败，避免产生“能接收但不能执行”的半配置服务。

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/v1/analyze` | 同步业务演示路径 |
| `POST` | `/v2/jobs` | 幂等创建并入队异步任务 |
| `GET` | `/v2/jobs/{job_id}` | 读取任务级生命周期快照 |
| `GET` | `/v2/jobs/{job_id}/trace` | 读取完整持久化审计轨迹 |
| `GET` | `/health` | 进程存活检查 |
| `GET` | `/ready` | PostgreSQL 与 Redis 就绪检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET` | `/console` | V1 研判控制台 |
| `GET` | `/trace` | V2 Job Trace 查看器 |

每个 HTTP 响应都带 `X-Request-ID`。调用方可传入不超过 128 字符的同名请求头用于关联；未传时由服务生成。HTTP Request ID、Job ID 和 Agent Trace ID 是三个不同层级的标识。

## 2. 创建任务

```http
POST /v2/jobs HTTP/1.1
Content-Type: application/json
Idempotency-Key: demo-event-001

{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requested_by": "demo-user",
  "event_id": "event-001",
  "query": "分析该事件的风险",
  "comments": [
    {
      "sample_id": "c-1",
      "text": "需要持续关注后续影响",
      "context": "可选的原帖上下文",
      "source_url": "https://example.com/synthetic/event-001"
    }
  ]
}
```

约束：

- `Idempotency-Key` 必填，长度 1–200；
- 每个 Job 需要 1–500 条评论，`sample_id` 在 Job 内唯一；
- 请求总字符数受安全预算限制，敏感自由文本在持久化前脱敏；
- `project_id` 必须已经存在，API 不隐式创建 Project。

首次成功创建返回 `202 Accepted` 和 `Idempotency-Replayed: false`。相同 Key 与相同规范化正文会返回原 Job，且不重复入队，响应头为 `true`。以下是任务快照的精简示例，完整字段以 `/docs` 为准：

```json
{
  "id": "6b50acb5-e11e-4f97-a38e-20bf8a7b9f30",
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requested_by": "demo-user",
  "idempotency_key": "demo-event-001",
  "status": "queued",
  "event_id": "event-001",
  "query": "分析该事件的风险",
  "request_payload": {},
  "result_payload": null,
  "error_code": null,
  "error_message": null,
  "attempt_count": 0,
  "recovery_count": 0,
  "created_at": "2026-10-16T04:00:00Z",
  "updated_at": "2026-10-16T04:00:00Z"
}
```

## 3. 查询状态

```http
GET /v2/jobs/6b50acb5-e11e-4f97-a38e-20bf8a7b9f30
```

任务状态含义：

| 状态 | 含义 |
|---|---|
| `queued` | 已持久化，等待 Worker |
| `running` | Worker 持有有效租约并执行 |
| `retrying` | 可恢复失败或租约过期，等待下一尝试 |
| `manual_required` | 自动结论暂停，等待人工复核 |
| `completed` | 正式结果完成 |
| `failed_closed` | 终态失败，不输出伪成功结果 |
| `degraded` | 合同保留的降级状态；当前成功 Worker 主要以 `manual_required` 表达可控降级 |

找不到 UUID 对应任务时返回 `404`。轮询方应对终态 `completed`、`manual_required`、`failed_closed` 停止自动轮询，并按业务策略处理人工复核。

## 4. 查询完整 Trace

```http
GET /v2/jobs/6b50acb5-e11e-4f97-a38e-20bf8a7b9f30/trace
```

顶层响应：

```json
{
  "job": {"id": "...", "status": "completed"},
  "runs": [
    {
      "id": "...",
      "trace_id": "...",
      "attempt": 1,
      "status": "completed",
      "version_snapshot": {},
      "input_state": {},
      "output_state": {},
      "worker_id": "worker-...",
      "heartbeat_at": "2026-10-16T04:00:03Z",
      "recovery_reason": null,
      "token_input": 0,
      "token_output": 0,
      "started_at": "2026-10-16T04:00:01Z",
      "finished_at": "2026-10-16T04:00:04Z",
      "checkpoints": [],
      "tool_calls": []
    }
  ],
  "human_reviews": [],
  "shadow_runs": []
}
```

排序保证：

- `runs` 按 `attempt` 递增；
- 每个 Run 的 `checkpoints` 与 `tool_calls` 按 `sequence_no` 递增；
- 人工复核与 Shadow 记录按创建时间递增。

`shadow_runs` 只是候选比较证据，不能被解释为正式输出。浏览器可打开 `/trace?job_id={job_id}` 直接载入同一响应。

## 5. 错误语义

| HTTP | 场景 | 处理建议 |
|---|---|---|
| `409` | 同一 Idempotency-Key 配置了不同请求 | 更换 Key 或恢复原请求，不能盲目重试 |
| `413` | 请求超过字符预算 | 缩小输入批次 |
| `422` | schema、安全策略或字段校验失败 | 修正请求，不应原样重试 |
| `503` | Job 已落库但 Redis 入队失败，或依赖未就绪 | 查看 `error_code=queue_unavailable` 和 `/ready` |
| `404` | Job 或 Trace 不存在 | 核对 Project/环境与 Job ID |

入队失败不会留下假 `queued`：已持久化 Job 会被更新为 `failed_closed`。Worker 内部超时、连接错误、429、5xx 和无效 JSON 可在尝试预算内进入 `retrying`；不可重试或预算耗尽会进入 `failed_closed`。

## 6. 安全与授权边界

当前入口执行请求预算、敏感文本脱敏、工具白名单、最大工具调用数和输出契约校验，但认证授权尚未实现。`requested_by` 目前仍来自请求，不等同于可信身份。Trace 包含业务输入、输出和工具审计数据，因此不能直接暴露在公网；生产部署必须由网关或应用层提供身份认证，并按 Project 限制读取权限。
