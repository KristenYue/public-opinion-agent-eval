# V2 部署与集成测试

## 1. 运行拓扑

`compose.yaml` 启动八个服务：

1. `postgres`：任务、Run、证据、工具调用和 checkpoint 的审计账本；
2. `redis`：ARQ 队列，启用 AOF；
3. `migrate`：一次性、按编号执行尚未应用的 migration；
4. `bootstrap`：幂等创建首个 Project，满足 Job 外键；
5. `api`：FastAPI，接收 V1 同步请求和 V2 异步 Job；
6. `worker`：领取队列任务、维护租约、调用现有 LangGraph 并保存结果。
7. `prometheus`：抓取 API 低基数运行指标；
8. `grafana`：自动加载 Prometheus 数据源和 API 概览面板。

启动顺序由健康检查和 `depends_on` 条件约束：PostgreSQL 健康后才迁移，迁移成功后才初始化 Project，初始化成功且 Redis 健康后才启动 API/Worker。

## 2. 本地启动

不要把密码写进仓库。PowerShell 示例：

```powershell
$env:POSTGRES_PASSWORD="生成一个随机强密码"
$env:GRAFANA_ADMIN_PASSWORD="生成另一个随机强密码"
docker compose config
docker compose up --build
```

如果密码包含 `@`、`:`、`/`、`#` 等 URI 保留字符，需先做 URL 编码，因为同一个值会进入 `DATABASE_URL`。

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
docker compose ps
docker compose logs migrate bootstrap api worker
```

`/health` 只证明 API 进程能响应；`/ready` 会实际执行 PostgreSQL `SELECT 1` 和 Redis `PING`。流量入口应使用 `/ready`。

Prometheus 指标地址是 `http://127.0.0.1:8000/metrics`，Prometheus UI 默认是 `http://127.0.0.1:9090`，Grafana 默认是 `http://127.0.0.1:3000`。Grafana 管理员密码必须由环境变量提供，仓库不设置可用默认值。

提交示例：

```powershell
$headers = @{ "Idempotency-Key" = "demo-request-001" }
$body = @{
  project_id = "11111111-1111-1111-1111-111111111111"
  requested_by = "local-demo"
  event_id = "event-demo"
  query = "分析事件舆情"
  comments = @(@{ sample_id = "c-1"; text = "需要持续关注后续影响" })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v2/jobs `
  -Headers $headers -ContentType "application/json" -Body $body
```

再次使用相同 Header 和相同 Body，应返回同一个 Job，并带 `Idempotency-Replayed: true`。相同 Key 配不同 Body 应返回 409。

## 3. 停止与数据处理

普通停止保留 PostgreSQL 和 Redis volume：

```powershell
docker compose down
```

不要把 `docker compose down -v` 当成普通停止命令；`-v` 会删除数据库和队列 volume，只能在明确接受丢失本地数据时使用。

## 4. CI 集成证据

GitHub Actions 的 `postgres-redis-integration` Job 会：

1. 启动真实 PostgreSQL 16 与 Redis 7 service containers；
2. 执行全部 migration；
3. 幂等初始化 Project；
4. 验证数据库与队列探针；
5. 验证 Job 幂等创建、Redis 入队、Worker 领取语义、租约 heartbeat、正式结果持久化与独立 shadow 记录。

本地普通测试明确排除 `integration` marker；有真实服务时可运行：

```powershell
.\.venv\Scripts\python.exe scripts\apply_v2_migrations.py
.\.venv\Scripts\python.exe scripts\bootstrap_v2_project.py
.\.venv\Scripts\python.exe -m pytest -q -m integration
```

## 5. Runtime shadow 灰度与回滚

shadow 默认关闭。镜像包含固定到 Runtime Platform 已验证提交 `0070d1a5cf2ae2f00bf356fb0aae903644299d3c` 的可选依赖，但 Worker 在关闭时不会导入或初始化它，也不会产生第二次图执行。

首次开启前先应用 `0003_shadow_runs.sql`，再只重启 Worker：

```powershell
docker compose run --rm migrate
$env:RUNTIME_SHADOW_ENABLED="true"
docker compose up -d --build worker
docker compose logs worker
```

开启后，正式结果仍只写 `analysis_jobs`/`agent_runs`；candidate 结果、失败或超时只写 `shadow_runs`。默认超时为 120 秒，Runtime checkpoint 默认写入容器内 `/tmp/opinion-agent-shadow/runtime.sqlite3`。该 checkpoint 仅服务 candidate 运行，不是正式恢复事实源。

第一回滚手段：

```powershell
$env:RUNTIME_SHADOW_ENABLED="false"
docker compose up -d worker
```

关闭开关不会删除历史 `shadow_runs`。开启会重复执行分析图，可能产生额外模型费用与延迟；在组合质量门禁完成前，只用于受控验证，不应直接全量开启。

## 6. 当前边界

- 当前机器没有 Docker，因此本次只完成配置静态校验和无服务单元测试；不能把它表述为“本机 Compose 已跑通”。真实服务结果以 CI 执行记录或装有 Docker 的机器验收为准。
- 集成测试验证真实 PostgreSQL 和 Redis，但不会调用付费 LLM，也不会声称验证外部模型供应商。
- Worker 健康检查只检查主进程存活；API `/ready` 才会检查两项依赖。生产环境还应采集 ARQ 队列积压、失败数和租约恢复数。
- Prometheus 当前采集 API 请求率、延迟和 V2 提交结果；节点耗时、Token、证据与工具错误的事实源仍是 PostgreSQL 审计表。Worker 多进程指标在增加独立 exporter 前不能假装已经覆盖。
- 当前恢复粒度是输入 checkpoint 重放，不是 LangGraph 节点级续跑。
- `requested_by` 仍是请求字段；接入认证后必须由服务端身份覆盖。
- 本地尚未运行真实 PostgreSQL shadow integration；是否通过以远端 CI 或具备 Docker 的环境为准。
