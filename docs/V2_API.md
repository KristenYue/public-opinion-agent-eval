# Production V2 API

本文是 `production-v2` 的当前 API 契约。交互式 schema 在服务启动后访问 `/docs`；部署与环境变量见 [V2_DEPLOYMENT.md](V2_DEPLOYMENT.md)。

## 1. 启用条件与公共端点

同时配置 `DATABASE_URL` 和 `REDIS_URL` 时，应用注册 V2 路由；此时还必须配置 `V2_AUTH_TOKENS_JSON`，否则进程会在启动时失败。两项 durable 依赖都未配置时只运行 V1；只配置其中一个会在启动时失败，避免产生“能接收但不能执行”的半配置服务。

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
X-API-Key: 从部署 Secret 注入的 opaque token

{
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requested_by": "客户端字段会被忽略并由服务端身份覆盖",
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
- `X-API-Key` 必填；服务端从 `V2_AUTH_TOKENS_JSON` 验证 token，并用其映射的 subject 覆盖正文中的 `requested_by`。
- `owner` 与 `analyst` 可创建任务；`viewer` 只能读取已授权 Project 的 Job/Trace。

首次成功创建返回 `202 Accepted` 和 `Idempotency-Replayed: false`。相同 Key 与相同规范化正文会返回原 Job，且不重复入队，响应头为 `true`。以下是任务快照的精简示例，完整字段以 `/docs` 为准：

```json
{
  "id": "6b50acb5-e11e-4f97-a38e-20bf8a7b9f30",
  "project_id": "11111111-1111-1111-1111-111111111111",
  "requested_by": "由 X-API-Key 映射的可信 subject",
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
X-API-Key: 从部署 Secret 注入的 opaque token
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
X-API-Key: 从部署 Secret 注入的 opaque token
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
| `401` | 缺少或无效 `X-API-Key` | 使用部署方安全发放的 token，不要把 token 放入 URL 或仓库 |
| `403` | token 对应主体不是该 Project 成员，或角色不允许写入 | 由受信部署管理员授予正确 Project 角色 |

入队失败不会留下假 `queued`：已持久化 Job 会被更新为 `failed_closed`。Worker 内部超时、连接错误、429、5xx 和无效 JSON 可在尝试预算内进入 `retrying`；不可重试或预算耗尽会进入 `failed_closed`。

## 6. 认证与 Project 级 RBAC

V2 使用 `X-API-Key` 与环境变量 `V2_AUTH_TOKENS_JSON` 的 token→subject 映射建立可信主体。Token 只应由 Secret Manager 或部署环境注入；它不会写入 PostgreSQL、日志、响应、OpenAPI 或 URL。比较使用恒定时间逻辑，避免直接的 token 字符串比较。

`project_members` 将 subject 绑定到 Project 和角色：`owner` 可创建/读取，`analyst` 可创建/读取，`viewer` 只可读取。创建 Job、读取 Job 与读取完整 Trace 都会查询成员关系；跨 Project 的 UUID 猜测返回 403，不泄露审计数据。正文 `requested_by` 保留是兼容字段，但始终被认证主体覆盖。

成员变更不提供公共 HTTP 管理端点。受信部署管理员在已应用 migration 后，通过 `scripts/manage_v2_project_member.py PROJECT_ID SUBJECT owner|analyst|viewer` 连接数据库完成；该脚本需要 `DATABASE_URL`，并应在受控运维环境执行。当前适配器是最小 API-token 身份边界；如需企业 SSO，可在网关验证 OIDC 后保持同一 subject 与 `project_members` 授权语义。
