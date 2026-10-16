# Production V2 全过程工程日志

> 目标：不仅留下最终代码，还保留“为什么这样设计、哪里失败过、怎样定位和验证”的完整学习路径。
>
> 维护规则：每个问题都记录现象、根因、排查过程、解决方案、验证证据和可复用知识；没有实际验证的内容不得写成“已完成”。

## 0. 项目边界与当前目标

原 V1 是已经冻结的舆情研判实验，包含跨事件评测、人工接管、故障注入和发布门禁。V2 不修改 V1 的数据、阈值和结果，而是在新分支补生产工程能力。

- V1 冻结提交：`d69b5c6`
- 本地冻结标签：`v1.0-frozen-2026-09-11`
- V2 开发分支：`production-v2`
- 当前阶段：PostgreSQL 审计数据契约、异步 Job API、幂等与 Redis/ARQ 分发

## 1. 如何确定应该继续哪个仓库

### 现象

工作区里同时存在：

- `舆情研判Agent_高质量重建版`
- `public-opinion-agent-demo`
- `本科毕设_情感分析_恢复版`
- `agent-reliability-eval`
- `fso-agent-benchmark`

如果直接在名字最像的目录里开发，很容易把功能加到公开 Demo 副本或旧基座中。

### 排查

逐个检查 Git 分支、最后提交、README、源码结构和当前未提交文件。确认：

- `舆情研判Agent_高质量重建版` 具备完整 `src/`、`tests/`、评测与 FastAPI；
- `public-opinion-agent-demo` 是精简公开演示；
- 其余三个仓库分别属于模型基座、评测层和 Runtime 实验。

### 结论

选择 `舆情研判Agent_高质量重建版` 作为旗舰应用 V2 的开发仓库。

### 可复用知识

多仓库项目不能只按目录名判断主仓库。至少要同时检查：Git 历史、README 定位、源码完整度、测试覆盖和工作区状态。

## 2. 如何保护冻结实验和已有未提交修改

### 现象

仓库处于非干净状态：README、冻结说明和演示视频已经有未提交修改。这些内容不是本轮 V2 新增，不能覆盖、删除或误算成自己的修改。

### 解决

1. 保留所有已有文件，不执行 `reset`、`checkout --` 或清理命令。
2. 从冻结提交创建 `production-v2` 分支。
3. 给提交 `d69b5c6` 创建 `v1.0-frozen-2026-09-11` 标签。
4. V2 代码放入独立的 `src/opinion_agent/v2/` 命名空间。

### 验证

`git status --short --branch` 显示当前位于 `production-v2`，原 README、冻结说明和视频仍然存在。

### 可复用知识

“新建分支”并不会自动处理未提交文件。切换前后都必须查看 `git status`，并明确哪些文件属于用户已有成果。

## 3. 为什么第一步先冻结数据契约，而不是立刻写 Worker

异步 API、Worker、人工复核页都要读写同一批状态。如果先分别实现，很容易出现：API 叫 `failed`、Worker 叫 `error`、页面又叫 `need_review`，最后无法查询和回放。

因此先冻结：

- 8 张 PostgreSQL 表；
- Job 状态机；
- 模型、Prompt、工具集和策略版本快照；
- 请求与人工复核的幂等约束；
- 回放需要的输入、输出和 Trace 字段。

对应文件：

- `src/opinion_agent/v2/contracts.py`
- `src/opinion_agent/v2/migrations/0001_auditable_jobs.sql`
- `tests/test_v2_contracts.py`

## 4. 问题：当前虚拟环境没有 SQLAlchemy/Alembic

### 现象

检查结果：`sqlalchemy=False`、`alembic=False`。

### 决策

第 1 周目标是“设计并冻结表与状态机”，不是必须引入 ORM。因此先提交原生 PostgreSQL migration 和独立领域契约，避免为了生成 8 张表提前增加大型抽象。

第 2 周选择 `psycopg` 的异步连接实现小型 repository，并把数据库、队列依赖放到 `production` extra 中：

```powershell
python -m pip install -e ".[production]"
```

### 可复用知识

ORM 不是持久化的同义词。项目初期先稳定 SQL 和领域状态，能降低后续更换 ORM 或迁移工具的成本。

## 5. 问题：批量补丁因源码上下文不匹配而整体失败

### 现象

准备修改 `src/opinion_agent/api.py` 时，补丁预期源码包含：

```python
from typing import Callable
```

实际代码是：

```python
from collections.abc import Callable
```

补丁工具拒绝整批修改，返回 `Failed to find expected lines`。

### 根因

补丁上下文来自错误假设，而不是文件真实内容。

### 解决

1. 确认失败后没有产生半截修改。
2. 按“新增文件”和“修改现有文件”拆分补丁。
3. 使用实际 import 行重新构造最小上下文。

### 可复用知识

补丁校验失败通常是保护机制，不应改用粗暴覆盖。应重新读取目标附近代码，缩小补丁范围。

## 6. 问题：pytest 无法创建系统临时目录

### 现象

旧 API 测试使用 `tmp_path` 时失败：

```text
OSError: could not create numbered dir ... Temp/pytest-of-29007
```

同时 `.pytest_cache` 也出现 `WinError 5`。

### 根因

当前 Windows 沙箱允许写项目工作区，但系统 Temp 和部分缓存路径不可写。这不是业务代码失败。

### 解决

把 pytest 临时目录显式放到项目内的忽略目录，并关闭缓存插件：

```powershell
python -m pytest ... --basetemp tmp\pytest-v2-20261015 -p no:cacheprovider
```

### 可复用知识

测试失败要先区分“断言失败”和“测试基础设施失败”。路径权限、临时目录和缓存错误不能被误报成代码回归。

## 7. 问题：wheel 构建被沙箱 Temp 权限阻止

### 现象

`pip wheel` 在创建 build tracker 时抛出 `PermissionError`，没有生成 wheel；后续检查脚本因拿不到文件又出现 `IndexError`。

### 根因

第一处错误是根因，第二处只是连锁错误。pip 强制使用了沙箱不可写的系统临时目录。

### 解决

在用户批准后于沙箱外执行同一条本地构建命令。构建成功，并用 `zipfile` 检查 wheel 内容。

### 验证

```text
migration_packaged True
opinion_agent/v2/migrations/0001_auditable_jobs.sql
```

### 可复用知识

阅读日志时先找第一个异常。后面的 `IndexError` 不是打包逻辑问题，而是“构建失败后仍尝试读取产物”的二次错误。

## 8. 问题：同步数据库加 `asyncio.to_thread` 在当前环境挂起

### 初始设计

第一版 repository 是同步 `psycopg`，服务层用 `asyncio.to_thread` 避免阻塞 FastAPI 事件循环。

### 现象

Job 测试进入第一条提交后不再前进。最小复现：

```python
asyncio.run(asyncio.to_thread(lambda: 42))
```

在当前受限 Windows 环境同样无法结束，证明不是 repository 业务逻辑导致。

进一步测试发现，连只包含 `asyncio.sleep(0)` 的 `asyncio.run` 在该沙箱也不能正常完成。

### 解决

代码层不再依赖线程池包装同步数据库：

- repository 协议改为原生 async；
- PostgreSQL 使用 `psycopg.AsyncConnection`；
- Service 直接 `await repository`；
- Redis/ARQ 本身也是 async；
- 测试中的 fake coroutine 不做真实 I/O，使用只允许“立即完成”的小型驱动器验证服务逻辑。

### 为什么这不是只为通过测试

原生异步数据库能减少线程池切换，也避免同步连接在高并发 API 中阻塞事件循环。沙箱问题促使实现改成了更一致的异步架构。

### 边界

测试驱动器只能用于不会挂起的 Fake，不可替代真实事件循环集成测试。Linux CI 和 Docker Compose 中仍需运行 PostgreSQL/Redis 集成测试。

## 9. 问题：FastAPI 路由对象不一定都有 `.path`

### 现象

测试遍历 `v2_app.routes` 并直接访问 `route.path` 时失败：

```text
AttributeError: '_IncludedRouter' object has no attribute 'path'
```

### 根因

当前 FastAPI/Starlette 版本在 `include_router` 后可能保留包装路由对象，不能假设列表中所有对象类型相同。

### 解决

测试改为读取 FastAPI 生成的 OpenAPI 契约：

```python
paths = set(app.openapi()["paths"])
```

这也更接近真正需要保证的外部 API 行为。

## 10. 当前已验证结果

截至本记录版本：

```text
28 passed
```

覆盖：

- 合法/非法 Job 状态迁移；
- 终态不能被重新打开；
- 版本快照指纹稳定；
- 8 张审计表存在；
- 相同幂等 Key 和相同请求只入队一次；
- 相同 Key 但不同请求拒绝；
- Redis 分发失败写入 `queue_unavailable`；
- Job 查询；
- 同一任务内重复 `sample_id` 拒绝；
- V2 路由按配置启用，V1 路由保持不变。
- 未配置 PostgreSQL/Redis 时 V2 默认关闭；
- 只配置其中一个依赖时拒绝启动；
- 同时配置时正确装配 PostgreSQL repository 与 ARQ dispatcher。
- Worker 原子领取任务，未领取到时不会重复执行；
- `completed` 与 `manual_required` 不会混淆；
- timeout、连接失败、429、5xx、坏 JSON 在预算内重试；
- 达到最大次数或输出契约错误时失败关闭；
- 版本快照不包含 API Key 或 Provider URL；
- Trace 的 Token、后端和 duration 能转换为持久化字段；
- ARQ 0.28 Worker 配置能够在显式环境变量下导入。

## 11. 问题：只配置数据库或只配置 Redis 会产生“半套系统”

### 风险

- 只有 PostgreSQL：任务能落库但永远没人消费；
- 只有 Redis：任务可能进入队列，但 API 没有持久化记录可供查询和恢复；
- 自动退回内存队列：开发时看似能用，重启后任务全部丢失。

### 解决

默认装配遵循“两个都配置，或者两个都不配置”：

- 两个都没有：只运行原有 V1，V2 路由不出现；
- 两个都有：装配 `PsycopgJobRepository + ArqJobDispatcher`；
- 只有一个：立即抛出配置错误，拒绝以不可靠状态启动。

### 可复用知识

生产系统的降级不能破坏核心承诺。异步任务的核心承诺是“已接受的任务可持久查询并有执行路径”，因此不能静默降级为内存实现。

## 12. 为什么 Redis 入队失败要写成 `failed_closed`

数据库写入发生在 Redis 入队之前，可能出现“数据库成功、队列失败”的部分成功状态。如果什么都不做，任务会永远停在 `queued`，用户会以为它仍在排队。

当前处理：

1. 先用幂等 Key 建立持久 Job；
2. 再入 Redis/ARQ；
3. 入队异常时，仅当 Job 仍为 `queued` 才原子更新为 `failed_closed`；
4. 记录 `queue_unavailable` 和截断后的异常类型/消息；
5. API 返回 503。

未来可以增加 Outbox 模式消除数据库与 Redis 的双写窗口；在此之前，明确失败关闭比伪装成排队中更安全。

## 13. 问题：旧 Trace 缺少绝对时间和标准化工具输入

### 现象

V1 的 `TraceEvent` 包含节点名、状态、`duration_ms` 和 `details`，但不包含每一步的绝对 `started_at`，也没有统一的 `request_payload`。

### 风险

如果用“整次持久化时间减 duration”伪造每一步开始时间，多个步骤会得到互相重叠且不真实的时间；如果把 `details` 填进请求列，会把输出元数据冒充成工具输入。

### 解决

- 保留真实的 `duration_ms`；
- V1 兼容路径把请求明确记为空对象；
- `details` 放入响应字段；
- 起止绝对时间暂时都使用持久化时刻，不声称可以恢复真实时间线；
- 后续修改 Trace Schema，直接在节点执行时记录真实 UTC 起止时间和经过脱敏的请求/响应。

### 可复用知识

可观测性字段不能靠事后猜测补齐。缺失数据应该明确标注缺失，而不是生成看似完整但不可验证的审计记录。

## 14. 问题：生产依赖声明后仍需验证真实版本 API

### 排查

安装 `.[production]` 后实际获得：

- `psycopg 3.3.6`
- `ARQ 0.28.0`
- `redis 5.3.1`

通过 `inspect.signature` 核验了 `create_pool`、`RedisSettings.from_dsn`、`enqueue_job`，并确认 `ArqRedis.aclose` 存在。`pip check` 返回无冲突。

### 结果

CI 安装范围已加入 `production` extra，并新增 Worker 导入测试。这样可以避免“单元测试都通过，但发布镜像缺少 ARQ/psycopg”的假通过。

## 15. 问题：当前机器没有 Docker

### 现象

运行 `docker version` 和 `docker compose version` 均返回命令不存在。

### 影响

不能在本机验证：

- migration 是否被真实 PostgreSQL 接受；
- `ON CONFLICT`、JSONB、UUID 和事务行为；
- Redis 入队后 ARQ 是否真实消费；
- API、Worker、PostgreSQL、Redis 的端到端状态变化。

### 当前处理

完成纯逻辑测试、生产依赖安装、API 签名核验和 `pip check`，但继续把真实容器集成列为未完成项。下一阶段添加 Compose 与 CI service containers 后再关闭这一缺口。

## 16. Worker 的故障分类与重试边界

当前可重试：

- Timeout；
- ConnectionError；
- HTTP 429；
- HTTP 5xx；
- 无效 JSON。

当前不可重试：

- 缺少 `analysis_report`；
- 未知 `review_status`；
- 返回值不是字典；
- 其他未分类异常。

重试条件还必须满足 `attempt_count < max_attempts`。否则即使错误本身可重试，也转为 `failed_closed`。这避免无限重试和持续消耗预算。

## 17. 尚未完成、不能提前声称的内容

- 真实 PostgreSQL migration 执行与回滚验证；
- 真实 Redis/ARQ 入队和 Worker 消费；
- 服务重启后的恢复；
- Docker Compose；
- PostgreSQL/Redis 集成测试；
- 全仓库回归测试在当前沙箱中的完整通过结果。
- `requested_by` 目前来自请求体；接入认证后必须由服务端身份覆盖，不能信任客户端自报身份。

这些项目只有获得可重复命令和结果后，才能从本节移到“已验证结果”。

## 18. 建议学习顺序

1. 先读 `contracts.py`，理解状态机为何是业务规则而不是数据库字符串。
2. 再读 migration，沿外键理解 Project → Job → Run → ToolCall/Evidence/Review。
3. 读 `jobs.py`，理解 repository 和 dispatcher 为什么要用 Protocol 隔离。
4. 读 `repository.py`，理解事务、`ON CONFLICT` 和请求哈希怎样实现幂等。
5. 读 `dispatcher.py`，理解 API 只负责可靠入队，不在 HTTP 请求内执行 Agent。
6. 最后读测试，从失败场景反推每个设计存在的原因。
7. 读 `worker.py`，理解“领取、执行、分类、重试、终止”为何彼此分离。
8. 读 `arq_worker.py`，理解业务执行器为何不直接依赖 ARQ。

## 19. 两层重试不能混为一谈

现有 Reviewer 节点内部已经对超时、连接错误、429 和 5xx 做有限重试；如果最终仍失败，节点会把错误写入 Trace，并将结果降级为 `manual_required`。这种情况下图正常结束，Worker 不应再次盲目重跑整个流程。

Worker 层重试处理的是没有被图内部吸收的执行失败，例如图调用整体超时、线程执行失败或其他顶层 Provider 异常。它受 `JOB_MAX_ATTEMPTS` 约束。

这样分层的原因：

- 节点重试成本较小，保留同一次 Agent Run；
- Worker 重试会创建新的 `agent_runs` attempt，成本更高；
- 已经安全降级到人工的结果不应被无限自动重跑；
- 每层都必须有独立预算，避免重试次数相乘失控。

## 20. 为什么包版本改为 `0.2.0.dev0`

冻结 V1 的包版本是 `0.1.0`。如果 V2 继续构建成同一版本，wheel、日志和问题报告将无法区分冻结版本与开发版本。因此 V2 分支改为 `0.2.0.dev0`：

- `0.2.0` 表示 API 和持久化能力发生了向前演进；
- `.dev0` 表示真实 PostgreSQL/Redis 集成和恢复验收尚未完成；
- 完成发布门禁后才能去掉开发后缀。

## 21. 问题：写了 checkpoint 不代表真的会恢复

### 最初缺口

第一版计划在运行开始时写 `input_replay`，但重试仍然从 `analysis_jobs.request_payload` 重新构造输入。这样 checkpoint 只是审计副本，没有参与恢复。

### 修复

当 `attempt_count > 1` 时，领取事务会：

1. 查找上一尝试最新的 `input_replay`；
2. 对规范化 JSON 重新计算 SHA-256；
3. 与 `state_sha256` 比较；
4. 缺失或不一致时拒绝执行；
5. 校验通过后把该状态作为新尝试的 `resume_state`。

### 可复用知识

恢复能力必须通过“读取路径”证明。只验证写入表中有记录，不能证明系统真的会使用该记录。

## 22. 问题：单文件 migration 脚本无法继续演进

### 现象

原脚本固定执行 `0001_auditable_jobs.sql`。新增租约字段和 checkpoint 表后，再次运行会重复创建旧表并失败。

### 修复

脚本现在：

- 创建 `schema_migrations` 账本；
- 自动发现打包的编号 SQL 文件；
- 按文件名排序；
- 每个 migration 使用独立事务；
- 已记录版本直接跳过。

### 边界

如果某个数据库曾经手工执行 `0001`、却没有 migration 账本，需要先人工核对并补登记，不能盲目重跑。

## 23. 租约为什么必须带 owner

只记录过期时间还不够。Worker A 超时后，Worker B 可能已经恢复并重新领取；如果 A 随后恢复运行并提交旧结果，就会覆盖 B 的新状态。

因此 heartbeat、成功提交和失败提交都同时校验：

- Job 仍是 `running`；
- `lease_owner` 仍等于当前 Worker；
- Run 的 `worker_id` 仍等于当前 Worker。

失去租约的旧 Worker 不再修改数据库，只请求 ARQ 重新投递。

## 24. 当前恢复能力的准确名称

当前实现是“租约检测 + 输入检查点重放恢复”，不是“LangGraph 节点级断点续跑”。原因是现有图使用 `builder.compile()`，没有持久化 checkpointer 和稳定 `thread_id`。

节点级续跑仍需：

- PostgreSQL LangGraph checkpointer；
- 每次 Job 固定的 `thread_id`；
- 节点之间杀进程的集成测试；
- checkpoint 保留、脱敏和清理策略。

在这些证据完成前，README、简历和演示都不能声称“从任意节点继续”。

## 25. 问题：`FIRST_EXCEPTION` 会让正常完成的任务一直等待

### 错误设计

Agent 执行任务和心跳循环并发运行，最初使用：

```python
asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
```

### 根因

心跳循环在正常情况下不会结束也不会抛异常；Agent 正常返回也不属于 exception。因此等待可能退化为“等所有任务完成”，而心跳永远不完成，形成死等。

### 修复

改为 `FIRST_COMPLETED`：

- Agent 先完成：取消心跳并保存结果；
- 心跳先因租约丢失结束：取消旧 Agent 执行，禁止旧 Worker 提交；
- `finally` 始终回收心跳任务，避免后台 Task 泄漏。

### 可复用知识

并发控制不能只看函数名是否“像需求”。必须分别推演每个 Task 正常完成、异常完成和永不完成三种路径。

## 26. 为什么没有改写旧 Dockerfile

### 发现的问题

旧 `Dockerfile` 服务于 V1 Gradio 演示：端口是 7860、安装 `demo` 依赖，并在镜像构建阶段下载 BGE 模型。如果直接替换：

- 会破坏已经冻结的 V1 演示命令；
- API 与 Worker 无法使用同一明确镜像入口；
- 无网络或模型仓库不稳定时，镜像构建也会失败；
- 模型下载和应用代码构建被不必要地绑定。

### 处理方式

保留旧文件，新增 `Dockerfile.v2`：

- 安装 `production` 依赖；
- 默认运行 Uvicorn 8000 端口；
- Worker 在 Compose 中覆盖 command；
- 默认使用 TF-IDF 检索，避免构建阶段下载模型；
- 使用非 root 用户运行；
- 镜像健康检查访问 `/ready`。

### 可复用知识

“升级”不等于覆盖旧入口。已经可用且用途不同的交付物，应并行保留并明确命名，直到新入口获得独立验收证据。

## 27. 存活检查与就绪检查必须分开

### 问题

原 `/health` 永远返回 `ok`。即使 PostgreSQL 或 Redis 已断开，编排器仍可能继续向 API 发送 V2 请求。

### 修复

- `/health` 保持轻量，只证明 Web 进程存活；
- `/ready` 对 PostgreSQL 执行 `SELECT 1`，对 Redis 执行 `PING`；
- 任一探针抛异常或返回 false，V2 就返回 HTTP 503；
- 日志只记录异常类型，不把可能包含密码的连接字符串写入日志。

### 设计边界

V1 未启用 durable service 时，`/ready` 返回 `mode=v1`。生产 V2 Compose 会同时注入两个连接地址，因此必须走实际依赖探针。

## 28. Job 外键导致“服务都启动了仍无法提交”

### 问题

`analysis_jobs.project_id` 正确地引用 `projects.id`，但全新数据库中没有 Project。若只运行 migration，第一次 Job 创建会得到外键错误。

### 修复

新增 `bootstrap_v2_project.py`，在 migration 成功后幂等插入一个显式 Project。它使用固定的开发默认 UUID，也允许通过环境变量覆盖。`ON CONFLICT DO NOTHING` 确保重启不会修改已经存在的项目元数据。

### 可复用知识

Schema 就绪不等于业务前置数据就绪。外键引用的租户、项目或系统账户必须有独立、幂等、可审计的 bootstrap 步骤。

## 29. Compose 中如何避免启动竞态

仅写普通 `depends_on` 只能约束容器启动顺序，不能证明数据库已经接受连接。当前链路使用：

- PostgreSQL/Redis 原生健康检查；
- `migrate` 等待 PostgreSQL `service_healthy`；
- `bootstrap` 等待 migration `service_completed_successfully`；
- API/Worker 等待 bootstrap 成功和 Redis 健康。

这使迁移失败成为显式启动失败，不会让 API 带着半套 Schema 接收请求。

## 30. 密码与配置问题

Compose 没有内置数据库默认密码，使用 `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}` 强制操作者提供。示例文件只有占位符，不包含可用凭据。

当前 `DATABASE_URL` 由该密码拼接；密码含 URI 保留字符时必须 URL 编码。这一限制已经写入部署文档。更成熟的生产部署应使用 Secret 文件或云 Secret Manager，并直接注入完整 DSN。

## 31. 真实集成测试与普通回归测试为什么分开

普通单元测试不应因为开发机没启动数据库而失败；但只用 Fake 又不能证明 PostgreSQL SQL、JSONB、锁和 ARQ API 真能工作。因此：

- 注册 `integration` marker；
- 普通 CI 执行 `-m "not integration"`；
- 独立 CI Job 启动 PostgreSQL 16、Redis 7；
- 真实执行 migration、bootstrap、幂等创建、入队、claim、heartbeat、finish 和读取。

集成测试故意不调用外部 LLM，避免把付费网络服务的不稳定性混入持久化链路验收。

## 32. 本阶段验证边界

当前 Windows 主机上执行 `docker --version` 已确认命令不存在，因此不能伪造 Compose 启动结果。本阶段可以本地验证的是：

- Python 语法；
- 无服务单元测试；
- Compose/Dockerfile 的关键结构静态断言；
- migration 与 bootstrap 脚本导入和参数边界。

必须等待 GitHub Actions 跑完，或在装有 Docker 的机器执行部署文档中的命令后，才能把“真实 PostgreSQL/Redis 集成通过”记为已验证事实。

## 33. 二次审查发现：探针本身也可能卡住

### 问题

容器健康检查命令设置了 5 秒超时，但这只会终止发起 HTTP 请求的进程。若数据库连接处于半开状态，API 内部的 `/ready` 协程仍可能继续等待；反复探测可能累积挂起请求。

### 修复

API 使用 `asyncio.wait_for` 给整个数据库 + Redis 就绪检查增加默认 3 秒总预算，可通过 `READINESS_TIMEOUT_SECONDS` 调整。超时同样返回 503。

### 可复用知识

客户端超时不能替代服务端预算。外部探针、API Handler 和底层驱动最好都有边界，避免任何一层无限占用资源。

## 34. 本阶段实际验证结果（2026-10-15）

本机已执行：

- `compileall`：通过；
- V2 contracts、Job service、Worker、ARQ 配置、部署与可观测性结构测试：32 项通过；
- `pip check`：无依赖冲突；
- `git diff --check`：无空白错误；
- Compose 和 GitHub Actions YAML：可被 YAML 解析器加载，服务与 CI Job 结构断言通过。

观察到三个非本阶段失败的警告：

1. LangGraph 序列化器未来默认值变更；
2. jieba 仍使用已弃用的 `pkg_resources`；
3. 当前 Windows 沙箱拒绝创建 `.pytest_cache`。

第三项不影响测试结果，只影响 pytest 缓存性能。前两项是上游兼容性债务，不能通过隐藏 warning 冒充解决。真实 service-container 集成仍等待 CI 或 Docker 主机执行，未计入上述 32 项通过结果。

## 35. 可观测性为什么分“运行指标”和“审计事实”

Prometheus 新增三组低基数指标：HTTP 请求数量、HTTP 延迟直方图、V2 提交结果。Grafana 自动加载请求率、P95 延迟和提交结果面板。

指标的 route 标签使用 FastAPI 路由模板，例如 `/v2/jobs/{job_id}`，不使用真实 URL。否则每个 UUID 都会创建一条新时间序列，最终造成高基数内存问题。

节点耗时、Token、证据、工具错误和版本快照继续写 PostgreSQL。原因是 Prometheus 适合聚合运行趋势，不适合保存“某个具体 Run 当时看到了什么”这种逐条审计证据。

## 36. 结构化日志的关联边界

API 每个请求会生成或接收最多 128 字符的 `X-Request-ID`，在响应头回传，并输出不含请求正文和凭据的 JSON 日志。Worker 在领取、完成、失败和丢失租约时输出 `job_id`、`run_id`、`trace_id` 和状态。

这里没有把 HTTP `request_id` 冒充成 Agent `trace_id`：前者关联一次网络请求，后者关联一次执行尝试。Job ID 是两条链路之间的业务连接点。

## 37. Observability 的诚实边界

Prometheus 当前只抓取 API 进程。Worker 没有为了“看起来完整”而把多进程内存 Counter 暴露成错误数据。Worker 可靠性目前通过结构化日志和 PostgreSQL 的 `agent_runs`、`tool_calls`、lease/recovery 字段审计。

若下一阶段需要 Worker 实时面板，应新增基于 PostgreSQL/ARQ 的独立 exporter，或部署统一 OpenTelemetry Collector，而不是把多个 Worker 的进程内指标当成全局总数。

## 38. 新依赖为什么会让已有虚拟环境突然失败

### 现象

`pyproject.toml` 已加入 `prometheus-client`，但第一次测试仍在导入阶段报 `ModuleNotFoundError`。

### 根因

editable 安装只让源码路径实时生效，不会在每次修改 `pyproject.toml` 后自动安装新依赖。仓库声明和当前 `.venv` 的实际内容出现了短暂差异。

### 修复与验证

1. 沙箱内安装先因网络代理限制失败；
2. 获得联网权限后安装 `prometheus-client 0.26.0`；
3. 重新执行 editable 安装以刷新发行包元数据；
4. 沙箱 Temp 目录权限再次阻止本地构建，改在获准的沙箱外环境完成；
5. 重跑后 32 项测试通过，`pip check` 无冲突。

### 额外发现

最初把 pytest、配置解析、`pip check` 和 `git diff --check` 放进一个 PowerShell 命令，最后一个命令成功会让整段最终退出码为 0，即使中间 pytest 已失败。之后改为单独执行关键测试，并在组合验证中逐项检查 `$LASTEXITCODE`。

### 可复用知识

不要只看一串命令最后显示的退出码。CI 脚本应使用遇错即停，或在每个关键阶段显式传播失败码；依赖清单变化后也必须重新同步环境和包元数据。

## 39. 可观测性补充后的最终复验（2026-10-15）

- 32 项 V2 非集成测试通过；
- `/metrics` endpoint 直接调用成功，并包含 `opinion_agent_http_requests_total`；
- 安装包元数据已包含 `prometheus-client`；
- Prometheus 配置、Grafana provisioning、dashboard JSON 均可解析；
- `pip check` 无冲突；
- `git diff --check` 无空白错误；
- Docker 仍不可用，因此八服务 Compose 运行结果仍保留为待外部验证项。

本阶段没有修改或删除用户原有的冻结记录、演示视频和未提交内容。

## 40. 为什么不能继续使用旧 RAG 报告

旧报告只有 12 条查询，而且查询经常直接包含目标事件标题；TF-IDF 达到 100% 并不意外。它没有无关问题、污染文档、冻结哈希和发布门槛，因此只能保留为 sanity benchmark，不能用作 V2 的 RAG 质量证据。

本阶段新建公开合成 `rag_eval_v1`，没有读取或发布被 `.gitignore` 隔离的私有微博事件卡。数据包含相关、无关和污染三类查询，并由 manifest 锁定 corpus 与标注文件的 SHA-256。

## 41. 问题：稀疏检索对任何输入都返回结果

### 根因

原 `TfidfEventRetriever` 总是按余弦相似度排序，即使所有分数为 0 也返回 `top_k`。这会让完全无关问题获得看似有出处的证据。

### 修复

新增可选 `min_score`。默认仍为 `None`，保证 V1 行为不被悄悄改变；V2 冻结评测显式使用 0.04。低于阈值时返回空结果，Agent 会把 evidence node 标为 degraded，而不是编造相关性。

## 42. 问题：检索内容会直接进入 Reviewer Payload

检索证据是外部数据，即使以 JSON 放在 user message 中，也可能包含诱导模型忽略规则或调用工具的文本。新增 `GuardedRetriever` 作为进入 LLM 前的信任边界：

1. 多取候选，避免剔除污染卡后没有正常替补；
2. 用稳定规则检测指令覆盖、提示词窃取、角色覆盖和工具命令；
3. 污染证据不进入 Reviewer；
4. Trace 只记录 ID 和命中规则，不复制恶意正文。

这只是已知模式防御，不等于解决所有 Prompt Injection。安全文档已明确这一边界。

## 43. 首次冻结 RAG 结果与失败案例

23 条查询的结果：

- 16 条相关查询：Recall@5、MRR@5、nDCG@5、Top-1 引用正确率、有证据率均为 100%；
- 4 条无关查询：拒绝 3 条，拒绝率 75%；
- 3 条污染查询：污染卡均被实际检测并拒绝，拒绝率 100%。

保留 Bad Case：询问快速排序的 `n02` 因“算法”一词误命中配送算法事件卡。该结果刚好达到冻结门槛，没有事后调阈值或删除样本。

## 44. 测试时再次遇到 Temp 权限问题

第一次定向 pytest 的多个 `E` 来自 Windows 沙箱无法在系统 Temp 创建 `pytest-*` 目录，不是检索断言失败。使用工作区内专用 `--basetemp .pytest-tmp-rag` 后，检索、RAG 指标和发布门禁 11 项测试全部通过。

含完整 FastAPI `TestClient` 的组合仍可能受当前沙箱事件循环限制，因此另外只运行了 API 中 3 个检索构建测试，均通过。测试范围和环境限制必须分别报告。

## 45. RAG 阶段合并复验（2026-10-15）

- V2、Retriever、RAG evaluation、Release readiness 共 43 项测试通过；
- API 中 3 项 Retriever 构建与 fallback 测试单独通过；
- `evaluate_rag_v1.py` 通过，冻结哈希与全部指标门槛有效；
- 总发布门禁通过，状态为 `ready_with_warnings`；
- `compileall`、`pip check`、`git diff --check` 均通过；
- 测试专用 basetemp 已在确认位于仓库内后清理；
- 真实 Docker Compose 和 CI service-container 结果仍未在本机验证。

总发布门禁继续保留两个 warning：仓库许可证仍待第三方资产条款核对后选择、本机没有 Docker。这两项没有被 RAG 阶段掩盖或降级。

## 46. 二次审查发现：评测配置与生产配置不一致

### 问题

冻结 RAG 脚本显式使用 `min_score=0.04`，但 `build_retriever()` 创建生产 TF-IDF 时仍使用类的兼容默认值 `None`。如果不修复，CI 证明的是一个会拒绝无关结果的候选配置，而线上实际不会拒绝。

### 修复

- `build_retriever()` 默认读取 `RETRIEVAL_MIN_SCORE=0.04`；
- Compose 和 `.env.example` 显式暴露该值；
- Run 的 toolset version snapshot 记录阈值，保证事后可解释；
- 允许显式配置 `disabled`、`none` 或空值回到兼容模式，但不能无记录地改变；
- 增加默认值和显式关闭两条测试。

### 可复用知识

评测代码、部署配置和版本快照必须指向同一个系统配置。指标再漂亮，如果评测对象不是实际上线对象，也不能形成生产证据。

## 47. PowerShell 非终止错误再次说明“最终退出码”不够

清理两个 pytest basetemp 时，其中一个目录已被 pytest 自动移除，`Resolve-Path` 因此报告非终止错误；PowerShell 仍继续执行后续验证并最终返回 0。随后单独枚举确认仓库中已经没有 `.pytest-tmp-*` 目录。

这不是产品代码错误，但说明自动化脚本若要求任何 PowerShell 错误都终止，应设置 `$ErrorActionPreference = 'Stop'` 或对可选路径先用 `Test-Path`。仅检查 `$LASTEXITCODE` 只能覆盖原生进程退出码，不能覆盖所有 PowerShell cmdlet 错误。

阈值一致性修复后追加验证：4 项 API Retriever 测试通过，Worker/Retriever/RAG/发布门禁相关 21 项测试通过，RAG gate、总发布 gate、compileall 和 diff 检查再次通过。

## 48. 为什么字段长度限制不等于请求预算

每条评论最多 5,000 字，但最多允许 500 条；所有字段各自合法时，总请求仍可能非常大。新增 `MAX_REQUEST_CHARS`，对完整规范化 JSON 计数，并在入库、入队或运行图之前拒绝。

该策略同时接入 V1、V2 和 MCP，避免攻击者通过另一个入口绕过。V2 HTTP 对超预算请求返回 413。

## 49. 工具白名单为什么在固定图里仍有意义

当前 LangGraph 节点由代码静态注册，模型不能任意调用函数。但如果只把这一点留在架构说明里，未来增加动态工具时可能无意间改变安全边界。

Worker 现在把它作为输出契约：Trace 数量不能超过 `MAX_TOOL_CALLS=8`，每个 node 必须在显式白名单。违反时使用 `security_policy_violation` 失败关闭且不重试。策略值同时写入 Run 的 policy version snapshot。

## 50. 危险操作确认的事实边界

实现了可测试的 `dangerous_tools + human_confirmed` 授权规则；缺少确认会抛 `HumanConfirmationRequired`。但生产白名单目前没有副作用工具，也没有审批 UI 或审批数据库状态机。

因此当前证据只证明“策略能够拒绝未经确认的危险工具”，不能声称“已经交付完整人工审批系统”。这一区分已经写入安全文档和 README。

## 51. 问题：只扫描字符串内容会漏掉敏感字段

第一版脱敏能识别 `api_key=...` 和长 Token，但 `{"api_key": "short-secret"}` 的值本身没有明显格式，会漏过。

修复为双层策略：

- key 是 `api_key`、`authorization`、`password`、`cookie`、`client_secret` 等时，整值替换；
- 其他任意字符串继续扫描邮箱、手机号、Bearer Token 和凭据赋值形式。

`requested_by` 暂时作为审计主体保留，且明确标注它目前仍是客户端自报字段；认证完成后必须由服务端 principal 覆盖。

## 52. 10 项安全门禁首次不是全绿

首次运行结果为 9/10。失败句子是“忽略之前所有指令”：规则支持“忽略之前的指令”和“忽略所有指令”，但没有覆盖“之前 + 所有”的组合。

处理方式是扩展检测规则并把原失败句加入固定回归，而不是修改测试句绕过问题。第二次执行达到 10/10。这个结果只代表确定性已知场景，不代表覆盖所有 Prompt Injection。

## 53. 安全治理阶段最终复验（2026-10-15）

- Governance、V2 Job、Worker、MCP、Retriever、RAG 和发布检查相关 56 项测试通过；
- 安全故障注入门禁 10/10 通过；
- RAG 冻结门禁通过；
- 总发布门禁为 `ready_with_warnings`，RAG 与安全治理均为 blocking check 且通过；
- `compileall`、`pip check`、`git diff --check` 通过；
- 工作区测试临时目录已使用 `Test-Path`、绝对路径边界和遇错即停方式清理。

仍保留的发布 warning：尚未在核对第三方资产条款后选择 LICENSE，以及当前主机没有 Docker。认证/RBAC、Project 数据隔离、完整审批状态机和执行中 Token/费用中断仍是下一阶段工作，不能算作已经完成。

## 54. 为什么 Runtime consolidation 放到新仓库

下一阶段需要把 FSO 的 provider-neutral loop 与 reliability eval 的成对回归思想汇总成平台。审计时发现两个来源仓库都已冻结且含用户未提交内容，直接重构会破坏基线，也会混淆旧项目和新能力的证据边界。

因此创建相邻独立项目 `agent-runtime-quality-platform`。两个冻结仓库全程只读，新实现不复制其源码；具体来源与许可证边界记录在新项目 `docs/SOURCE_BOUNDARY.md`。

## 55. Runtime Platform 0.1 基线

新平台已经实现：

- provider-neutral `Planner Protocol`；
- 同步/异步工具注册、allowlist 与危险权限；
- `asyncio.gather` 工具批次并发；
- `max_steps + max_tool_calls` 双预算；
- SQLite checkpoint 与 SHA-256 完整性检查；
- 显式暂停、危险工具暂停、批准/拒绝和跨 Runtime 实例恢复；
- Run/Step/ToolCall/Error 统一 Trace；
- baseline/candidate 严格成对回归门禁。

它目前是独立内核，还没有接入舆情业务代码，不能把其测试结果算作舆情 Agent 的发布证据。

## 56. 测试卡住的真正原因不是状态机

完整测试先通过 5 个同步用例，随后在第一个 `asyncio.run` 卡住。通过 pytest 的 `faulthandler_timeout=8` 得到堆栈，线程停在 Windows ProactorEventLoop 创建内部 socketpair 的 `accept`，尚未进入 Runtime 业务代码。

经授权在沙箱外用相同 Python、代码和测试命令复验，初版 16 项通过；加入步骤预算回归后最终为 17 项通过。这个过程说明遇到 hang 应先取线程栈，再区分环境初始化、网络/锁等待和业务无限循环。

## 57. src layout 的 import 差异

pytest 通过是因为 `pyproject.toml` 为测试配置了 `pythonpath = ["src"]`。普通 Python 在项目尚未安装时不会自动搜索 `src`，所以额外 import 检查第一次报 `ModuleNotFoundError`。

本轮不修改共享虚拟环境，改用显式源码路径完成 TOML 与 import 验证。正式使用应执行 `pip install -e ".[dev]"`；未来 CI 还应在干净 venv 中验证安装产物。

## 58. Runtime Platform 阶段复验（2026-10-15）

- 新项目完整测试 `17 passed in 0.30s`；
- `compileall`、`pip check`、TOML 解析和包 import 通过；
- 4 个测试临时目录经绝对路径边界检查后清理；
- 两个冻结来源仓库的原有 dirty 状态保留；
- 完整架构、来源边界、问题与解决过程见新项目 `docs/ARCHITECTURE.md`、`docs/SOURCE_BOUNDARY.md`、`docs/ENGINEERING_LOG.md`。

尚未完成：真实模型 adapter、任意 crash replay/lease/幂等协议、认证/RBAC、持久化审批主体、OTel exporter 和新项目许可证。下一阶段接入舆情 Agent 时必须重新跑两边门禁，不能用独立内核测试替代集成验证。

## 59. Runtime Platform 0.2：租约与恢复边界

相邻 `agent-runtime-quality-platform` 新增：

- SQLite run lease、owner 与 heartbeat；
- `run_id:step_no:tool_index` 确定性幂等键；
- tool result ledger 与完整性哈希；
- `inflight_action` 先记意图再执行；
- completed trace 缓存恢复；
- 非 replay-safe 写入/计算的不确定恢复失败关闭。

这里没有宣称 exactly-once。外部副作用发生后、本地 tool ledger 写入前崩溃，SQLite 无法判断副作用是否已发生；必须靠外部幂等键、事务 outbox 或 fencing token进一步解决。

## 60. 问题：30ms 超短租约首次误判失租

23 项首测中 22 项通过，长工具 heartbeat 用例失败。续租 SQL 原本要求 owner 相同且续租瞬间尚未过期；Windows 调度稍迟即使无人接管也会失败。

修复为原子校验 owner：未接管时允许同 owner 迟到续租，接管后 owner 已变化，旧 worker 仍不能续租。增加迟到续租和接管后拒绝回归，随后 24 项通过。

## 61. 舆情 Agent 薄 adapter

新平台读取本项目真实 `AnalyzeRequest`、`AgentState`、`build_opinion_graph` 和 worker 契约，新增不复制业务源码的 adapter：

- 输入限制与 V1 API 对齐；
- 通过 `graph_provider().invoke(state)` 调用现有图；
- 同步 LangGraph 在 worker thread 中运行；
- 输出校验 event_id、analysis_report、tool_traces、errors；
- 安全脱敏/校验通过 transform 注入；
- 图标记为 `compute`，因为模型调用可能付费、非确定，不能像普通只读查询那样盲目 replay。

平台还没有替换本项目的 V2 JobExecutor；当前是可组合、可测试的薄接入层。

## 62. 真实跨仓库集成验证

不仅使用 FakeGraph，还显式加载本仓库的 `build_opinion_graph(StubClassifier)`，经新 Runtime 跑通：

1. sentiment_classifier；
2. sentiment_aggregator；
3. briefing_composer；
4. analysis_report 与 tool_traces 输出校验。

这条测试证明真实图契约可连接，但使用的是确定性 StubClassifier，不代表真实模型、PostgreSQL、Redis 或 Docker 已组合验证。

## 63. 二次审查与测试夹具问题

恢复时如果旧 checkpoint 引用已删除工具，第一版会泄漏注册表 `ValueError`。已改为持久化 `tool_not_allowed` 并失败关闭。

新增回归首次又因手工 `run_id="tool-drift-run"` 不符合 UUID 契约而失败。没有放宽生产模型，而是修正测试夹具为合法固定 UUID。经验是测试状态也必须服从真实持久化契约。

## 64. Runtime Platform 0.2 最终复验（2026-10-15）

- 完整测试（含真实舆情图）：`29 passed, 2 warnings in 5.75s`；
- `compileall`、`pip check`、TOML 与 adapter import 通过；
- 6 个测试临时目录经绝对路径边界检查后清理；
- Runtime Platform 版本为 `0.2.0.dev0`；
- 舆情业务源码未改，仅本工程日志追加本阶段事实。

两条依赖 warning：LangGraph serializer 默认值未来会变化、jieba 间接使用已弃用 `pkg_resources`。下一步优先做外部幂等键/fencing token 或 V2 JobExecutor 灰度接入；接入前应先写 ADR，避免和本项目现有 PostgreSQL lease 重复叠加。

## 65. ADR：V2 与 Runtime Platform 的所有权边界

已在 Runtime Platform 新增 `ADR-0001`。结论是不把完整 SQLite Runtime 直接嵌套进本项目 `JobExecutor`：本项目 PostgreSQL repository 继续作为生产 Job/Run lease、heartbeat、重试和状态迁移的唯一事实源。

原因是直接嵌套会产生双 lease、双 retry、两个恢复 actor，并且 worker 本地 SQLite 无法承担跨容器协调。正式接入前必须先抽象 backend、实现 PostgreSQL adapter，并规划 shadow 与回滚开关。

## 66. 外部幂等上下文与故障注入

Runtime Platform `0.2.1.dev0` 新增 `ToolExecutionContext`，把稳定的幂等键、run/step/tool index 和 lease owner 通过受保护通道交给 opt-in 工具。Planner 参数不能覆盖 `runtime_context`。

故障注入模拟远端提交成功、本地记账前崩溃：恢复后 handler 再次被调用，但收到同一个 key，假远端只保留一次副作用并返回去重结果。该证据说明外部幂等协议有效，不代表没有外部协议时也能 exactly-once。

## 67. Runtime Platform 0.2.1 复验（2026-10-15）

- 完整测试（含真实舆情图）：`32 passed, 2 warnings in 13.25s`；
- `compileall`、`pip check`、TOML 与新上下文 import 通过；
- 测试临时目录已按边界规则清理；
- 本项目业务代码和 V2 JobExecutor 未改动。

下一硬门槛仍是 fencing token 与 PostgreSQL backend abstraction。完成之前，adapter 只能用于离线或 shadow 设计，不能宣称进入生产执行路径。

## 68. Runtime Platform 0.3：异步 backend boundary

Runtime 已从直接依赖 SQLite 改为异步 `RuntimeBackend` Protocol，覆盖 checkpoint、lease 与工具幂等账本。原 SQLite store 通过 `AsyncSQLiteBackend` 使用 `asyncio.to_thread`，避免同步数据库操作阻塞事件循环。

构造时 `checkpoints=` 与 `backend=` 必须二选一；Runtime 内部只访问 backend。读取 `get()` 也改为 async。该边界为未来 PostgreSQL adapter 服务，但当前并没有声称 PostgreSQL 已实现。

## 69. 二次审查：falsy backend

初版使用 `backend or fallback`，可能把显式传入但 `bool(backend) == False` 的扩展实现错误替换。已改为 `is not None`，并用 Falsy backend 回归验证。

## 70. Runtime Platform 0.3 复验（2026-10-15）

- 完整测试：`35 passed, 2 warnings in 5.39s`；
- backend-only、唯一入口和 falsy backend 测试通过；
- `compileall`、`pip check`、TOML/backend import 通过，测试临时目录已清理；
- 版本为 `0.3.0.dev0`；
- 舆情业务执行路径仍未改动。

下一步是实现 PostgreSQL backend 与 migration，但在连接现有 V2 repository 前需要先对表所有权、事务边界和 fencing token 写第二份 ADR。

## 71. Runtime Platform 对现有 V2 PostgreSQL 的审计结论

Runtime 接入前读取了本项目两份 migration、`PsycopgJobRepository` 和真实 Postgres/Redis integration test。结论：本项目 `run_checkpoints` 是业务 attempt 的 replay 边界，不应被 Runtime Planner step checkpoint 复用。

Runtime 新 migration 只创建 `runtime_checkpoints`、`runtime_run_leases`、`runtime_tool_results`，不 ALTER 本项目 `analysis_jobs/agent_runs/run_checkpoints/tool_calls`。

## 72. ADR-0002 与 fencing token

Runtime 的 SQLite/PostgreSQL lease 均升级为 `LeaseGrant(owner, fencing_token)`。首次 token=1，过期/释放后接管递增；renew/release 匹配 owner+token；token 进入外部工具上下文。

ADR-0002 仍将生产状态标为 blocked：checkpoint 和 tool ledger 写入尚未在 SQL 中校验 token，完整 stale-write fencing 尚未完成。

## 73. PostgreSQL backend 的证据边界

已实现异步 psycopg backend、独立 migration、哈希验证、原子 lease upsert 和 SQL 契约测试。最终结果：`42 passed, 1 skipped, 2 warnings in 5.59s`。

skipped 项是需要 `RUNTIME_DATABASE_URL` 的真实 PostgreSQL 生命周期。本机没有 Docker/专用 DSN，因此目前不能声称真实 PostgreSQL 已跑通。舆情 V2 业务代码仍未接入或修改。

下一步是让 backend checkpoint/tool-result 写入携带 LeaseGrant 并拒绝 stale token，然后在真实 PostgreSQL 上做双 worker 接管竞争；完成前不能进入 V2 shadow。

## 74. Runtime Platform 0.4.1：stale-write fencing

Runtime backend 的 checkpoint/tool-result 写方法现已强制携带 LeaseGrant。SQLite 在单事务、PostgreSQL 在单条条件 SQL 中校验当前 owner+token；不匹配会转换为 `RuntimeLeaseLost`。

故障注入让新 worker 在旧工具执行期间接管。旧工具随后虽返回成功，但 tool Trace 写入被拒绝，证明旧代际不能覆盖新状态。

首测再次发现 30ms TTL 的墙钟抖动：没有接管却因过期瞬间拒绝写。修复为校验 owner+token 代际；真实接管必然递增 token，因此安全性不依赖精确墙钟调度。

最终结果：`45 passed, 1 skipped, 2 warnings in 5.33s`。真实 PostgreSQL 双 worker 测试仍因无 DSN 跳过，故生产状态继续 blocked。

收尾静态验证也已完成：Runtime Platform 的 `src/`、`tests/` 通过 `compileall`，`pip check` 无破损依赖，TOML 配置与新增公共导入正常。2 个 pytest 临时目录在绝对路径边界检查后删除，复查无残留；本舆情项目业务执行路径仍未改动。

## 75. Runtime Platform 0.5.0：连接池与真实竞争测试入口

继续审计时发现 PostgreSQL tool trace SQL 遗留 `expires_at > CURRENT_TIMESTAMP`，与已确定的“以 owner+token 判断代际”规则冲突。已删除该墙钟条件并增加回归，避免没有接管时因调度抖动误拒绝结果。

Runtime PostgreSQL backend 新增显式 `open/close`、异步上下文和可配置的 `psycopg_pool.AsyncConnectionPool`。连接池用 `open=False` 创建并 `open(wait=True)`，让连接问题在启动阶段暴露；当前环境没有 pool 包和真实 DSN，因此只完成 fake-pool 生命周期契约验证，未声称真实池通过。

可选真实集成测试已升级：两套独立连接池会并发争抢已释放 lease，验证唯一 winner、token 递增、旧 grant 写入拒绝和 winner 状态读回。无 DSN 时仍明确 skip。

首次完整测试因 Windows 默认 pytest 临时目录拒绝访问产生 31 个 setup error；改用项目内 `--basetemp .pytest-tmp-v050` 后最终为 `51 passed, 1 skipped, 2 warnings in 5.61s`。舆情 V2 正式 JobExecutor 仍未切换或 shadow 接入。

## 76. 阶段路线校准：停止扩建内核，转向证据闭环

阶段完成后重新对照最初六周计划、Runtime 两份 ADR、当前代码、CI、Compose 和 Git 状态。结论是方向没有跑偏：冻结 V1 得到保留，舆情 V2 的生产工程主体先完成，Runtime 随后补足第 5 周要求的并发、checkpoint、恢复、人工中断、统一契约和舆情场景适配。

但当前已到拐点。若继续增加 Runtime 存储实现、框架或 Multi-Agent，会削弱“舆情旗舰应用 + Runtime 可靠性平台”的证据链。下一阶段固定为：

1. Runtime CI 中跑真实 PostgreSQL 双连接池竞争；
2. 实现默认关闭、失败隔离、不写正式结果的 V2 shadow；
3. 固化版本化舆情 Runtime 任务集并接入组合门禁；
4. 最后再做 Trace 页面和交付包装。

Runtime 仓库尚无初始 commit、全部文件 untracked，也是当前可复现性风险；本轮没有擅自提交。详细逐项对照、风险和验收线见 `docs/V2_ROADMAP_ALIGNMENT_2026-10-15.md`。

路线文档验证首次因脚本仍位于 Runtime 工作目录而读取失败；切换到本仓库后，结论、P0 和 shadow 关键内容断言通过。该问题只影响验证命令路径，不影响文件内容。

## 77. P0 进度：Runtime CI 已配置，尚未远端执行

Runtime Platform 新增两个 GitHub Actions job：普通单元/契约回归，以及带 PostgreSQL 16 service 的真实数据库集成。后者显式安装 pool 依赖、设置测试 DSN、执行 migration/连接池/双 owner 接管测试并上传 JUnit。

新增工作流契约测试，防止关键 service、DSN、依赖、测试入口或报告上传被意外删除。本地完整回归为 `53 passed, 1 skipped, 2 warnings in 5.56s`。

证据边界保持不变：Runtime 仓库还没有初始 commit，也没有远端 Actions run，所以只能认定“CI 配置完成”，不能认定“真实 PostgreSQL CI 已通过”。P0 的剩余动作是形成可评审提交并取得远端绿色结果；在此之前不推进 shadow 已验证状态。

## 78. Runtime 初始提交与单一作者审计

维护者确认仓库只保留本人一个作者后，Runtime 初始提交已创建。提交前完成敏感信息扫描、忽略文件核对与 staged diff 检查；`git diff --check` 首次发现工程日志两处行尾空格，修复后通过。

提交后的 Git metadata 和 shortlog 均显示唯一作者、Author 与 Committer 为 `KristenYue <yueyt1112@163.com>`，没有 AI 或其他协作者 trailer。

当前剩余阻断是外部仓库状态：Runtime 没有 remote，GitHub CLI 的 `KristenYue` token 已失效。需要维护者重新登录并选择 public/private 后创建远端或提供 URL；push 之后才能观察真实 PostgreSQL CI。

## 79. GitHub 登录完成，但远端仓库尚未创建

维护者完成操作后进行只读核验：`gh auth status` 已显示 `KristenYue` 登录成功，token 具备 `repo` 与 `workflow` scope；但本地 `git remote -v` 仍为空，GitHub API 查询 `KristenYue/agent-runtime-quality-platform` 返回 404。

进一步检查账号仓库列表，只发现既有 `fso-agent-runtime-benchmark`，没有名称包含 Runtime Platform 的新仓库。结论是本次只完成了 GitHub 登录，尚未执行创建仓库和 push。下一步向维护者提供单条 `gh repo create ... --source . --remote origin --push` 命令；执行后再核验远端 SHA、唯一作者和 Actions。

## 80. Runtime 首次 CI：真实 PostgreSQL 通过，unit 隔离失败

维护者随后成功创建公开仓库并上传；远端 SHA 与本地一致，作者仍只有 `KristenYue`。

首次 Actions run `38742299975` 总体红色，但 `postgres-integration` job 实际全绿，已经提供 migration、真实连接池和双 owner fencing 接管证据。失败的是只安装 `.[dev]` 的普通 unit job：fake-pool 测试虽然替换了 pool loader，却仍调用真实 psycopg 获取 `dict_row`。本机已安装 psycopg，导致此前没有暴露。

修复方案是让单测同时替换 psycopg loader，并断言 fake row factory 被传给池。这样普通 job 保持无数据库依赖，真实 PostgreSQL 仍由独立 job 验证。修复复跑绿色前，不把整体 CI 标为通过，也不推进 shadow。

修复后的本地定向测试为 `14 passed in 0.19s`，完整 Runtime 套件为 `53 passed, 1 skipped, 2 warnings in 15.81s`。下一步只提交并 push 这次隔离修复，再以新的 Actions run 判断整体门禁；旧红色 run 不删除，保留为问题发现证据。

## 81. Runtime 第二次 CI 全绿，P0 完成

修复提交 push 后，Actions run `38742915643` 全绿：unit job 为 `52 passed, 2 deselected in 0.96s`，真实 PostgreSQL job 为 `1 passed in 0.47s`，两份 JUnit 均已上传。远端 SHA、本地 SHA 和 `origin/main` 一致，作者仍只有 `KristenYue`。

日志里有一条非阻断 cache 提示：两个并行 job 竞争相同 pip cache key，其中一个 post-job 无法重复保存缓存；job conclusion 仍为 success。这不影响代码或测试，但作为 CI 环境现象保留记录。

P0 的仓库、作者、普通回归和真实 PostgreSQL证据现已闭环。下一阶段正式转入 P1：只实现默认关闭、shadow 失败隔离和独立结果边界，不直接替换正式 `JobExecutor` 结果。

## 82. P1a：V2 shadow 进程内安全边界

本阶段先完成 shadow 的最小安全边界，不同时引入数据库 migration、环境变量装配和 Runtime candidate。新增 `ShadowExecutor`、`ShadowRunner`、`ShadowSink` 与不可变 `ShadowRecord`；`JobExecutor` 仅在构造时显式注入 shadow 才启动它，因此现有生产构造路径默认零调用。版本从 `0.2.0.dev0` 提升为 `0.2.1.dev0`。

正式路径仍是唯一能够调用 Job repository 完成状态迁移和写入正式结果的执行路径。shadow 得到正式输入的深拷贝，其返回值不会交给 `finish_execution`；candidate 即使修改输入、失败或超时，也不能替换正式结果。shadow sink 只接收经过脱敏的独立记录；sink 自身失败也只记录日志，不向正式路径传播。取消信号仍重新抛出，避免吞掉 worker 的协作式关闭。

实现过程中发现并解决的问题如下：

1. 初版补丁把 `finally` 放到了同一 `try` 的 `except` 之前，形成非法 Python 结构。该问题在运行测试前的代码复查中发现；随后把 shadow `observe` 移到完整 `try/except/finally` 的最终 `finally`，再通过 `compileall` 验证语法。这个问题没有进入测试结果或提交。
2. 第一次在受限 Windows sandbox 中运行定向 pytest 时，只输出测试点后不退出。终止该进程后，改在相同项目和虚拟环境、但不受该 sandbox 进程约束的执行环境复跑，结果为 `16 passed, 1 warning in 0.18s`。warning 是 pytest 无法写 `.pytest_cache`，与业务逻辑无关。
3. 第一次完整回归没有排除标记为 integration 的 PostgreSQL/Redis 测试，结果为 `153 passed, 1 failed, 6 warnings in 18.34s`；唯一失败是当前 shell 没有 `DATABASE_URL`，测试收集环境因此触发 `KeyError`，并非 shadow 回归。使用项目约定的 `-m "not integration"` 重跑后为 `153 passed, 1 deselected, 5 warnings in 28.67s`。
4. 完整回归保留的 warning 分别来自 LangGraph serializer 未来默认值、jieba 间接使用弃用的 `pkg_resources`、Starlette `TestClient`/httpx 兼容层、旧版 XGBoost pickle，以及 pytest cache 权限。它们均为既有依赖或本机缓存现象，本阶段没有用屏蔽 warning 的方式伪造绿色结果。
5. 收尾代码复查发现 `ShadowExecutor.start()` 会在创建异步任务前同步深拷贝输入；若深拷贝或任务创建失败，异常原本会在正式 runner 启动前向外传播。已在 `JobExecutor` 边界捕获该同步启动异常、记录 `shadow_start_failed`，并继续正式执行；新增回归确认此时不会调用 observer，正式 Job 仍为 completed。

新增测试明确验证：默认不注入时 candidate 不会运行；candidate 收到深拷贝且不能替换正式结果；同步启动失败、candidate 失败与 sink 失败不影响正式成功；超时会写入 `timed_out` shadow 记录但正式状态保持不变。

补强后的最终定向测试为 `17 passed, 1 warning in 0.21s`；最终非集成完整回归为 `154 passed, 1 deselected, 5 warnings in 13.39s`。随后 `compileall`、`pip check`、TOML 版本与公共导入检查均通过。测试目录采用项目内 `--basetemp`，完成后按绝对路径边界检查并删除；`.pytest_cache` 权限 warning 仍作为本机环境现象保留。

阶段校准结论：P1a 已完成，方向没有跑偏，但不能据此宣称生产 shadow 已启用或独立 PostgreSQL 审计已完成。下一步固定为 P1b：默认关闭的环境开关、独立 `shadow_runs` 持久化与 ARQ worker 装配；真实 PostgreSQL 集成测试通过之前不进入 P2。

## 83. P1b：默认关闭的 Runtime shadow 部署接线

新增 migration `0003_shadow_runs.sql`，只创建独立 `shadow_runs` 表和查询索引，不 ALTER `analysis_jobs` 或 `agent_runs`。表通过 `job_id` 与 `official_run_id` 外键建立可追溯关系，但正式状态和结果仍只由原 repository 更新；同一 `official_run_id + candidate_name` 使用唯一约束，sink 通过 `ON CONFLICT DO NOTHING` 保留第一条审计记录，避免重复交付覆盖历史。

新增 `PsycopgShadowSink` 和 `RuntimeAdapterShadowRunner`。runner 只把 `event_id/query/comments` 映射给 Runtime adapter，不透传正式路径内部字段；只有 Runtime 状态为 completed 且 result 为字典时才形成成功记录。Runtime Platform 依赖固定到已取得绿色 CI 的提交 `0070d1a5cf2ae2f00bf356fb0aae903644299d3c`，避免浮动 main 导致跨仓库接口漂移。项目版本提升到 `0.2.2.dev0`。

ARQ Worker 新增严格布尔开关 `RUNTIME_SHADOW_ENABLED`。缺省和 Compose 默认均为 `false`；关闭时直接返回 `None`，不会导入可选 Runtime 包、创建 adapter 或执行第二次图。开启时才装配 Runtime adapter、独立 PostgreSQL sink、有界超时和独立 SQLite checkpoint 路径。Docker 镜像安装固定的 `shadow` extra，使开启行为在同一镜像中可复现；第一回滚手段是把开关设回 false 并重启 Worker。

本阶段遇到并解决的问题：

1. 审计 Runtime `RunResult` 后继续读取主项目 worker/env 文件时，命令工作目录仍停留在 Runtime 仓库，产生三个 `Cannot find path`。修复方式是显式切回舆情项目绝对工作目录后重跑；该问题只影响检查命令，没有修改文件。
2. 主项目虚拟环境没有安装尚未发布到 PyPI 的 Runtime 包。部署依赖因此没有写成浮动包名，而是使用 GitHub 远端完整提交 SHA 的 ZIP 依赖；普通单测通过 loader 注入验证关闭/开启装配，跨仓库契约测试则显式把相邻 Runtime `src` 加入 `PYTHONPATH`，真实调用该提交的 adapter。
3. 首版 shadow 异常记录只截断 `str(exc)`，尚未脱敏；若 provider 把 key 写进异常，可能落入 `shadow_runs.error_message`。已改为先调用 `redact_sensitive` 再截断，并增加 `api_key=top-secret` 回归，确认明文不会进入记录或启动失败日志。
4. 本地没有 Docker/真实 PostgreSQL，因此没有伪造 P1 完成结论。真实 integration 已扩展为应用 migration、写入并读回 `shadow_runs`，同时断言正式 `analysis_jobs.result_payload` 保持原值；该项等待远端 PostgreSQL 16 CI 执行。

验证结果：首次 P1b 定向测试为 `30 passed, 3 warnings in 4.67s`；补齐异常脱敏后，最终非集成完整回归为 `163 passed, 2 deselected, 5 warnings in 12.41s`。相邻仓库真实 Runtime adapter 契约测试为 `1 passed, 1 warning in 0.23s`。`compileall`、`pip check`、TOML 版本、公共导入和固定 shadow dependency 检查均通过。warning 仍是既有 LangGraph、jieba、Starlette、XGBoost 与 pytest cache 环境提示。

路线复核结论：P1b 的代码、默认关闭、回滚和测试入口已经完成，但“V2 shadow 已验证”仍差远端真实 PostgreSQL integration 证据。该 CI 绿色之前不进入 P2，也不建议开启真实流量 shadow。

## 84. Production V2 本地提交准备

为触发远端 PostgreSQL shadow integration，对当前累计变更做提交前审计。当前分支为 `production-v2`，远端 `origin` 指向维护者的 `KristenYue/public-opinion-agent-eval`；Git 身份为 `KristenYue <yueyt1112@163.com>`。历史记录中还出现过显示名 `YUTING YUE`，但邮箱相同，属于同一维护者身份；本次不添加 `Co-authored-by` 或其他作者 trailer。

高置信凭据扫描未发现 GitHub token、OpenAI 风格 key、AWS access key 或私钥头。累计暂存范围为 68 个文件、6866 行新增与 24 行删除，覆盖 Production V2、RAG/安全门禁、部署、测试和工程文档；4.27 MB 离线演示视频在 GitHub 单文件限制内。`git diff --cached --check` 通过。

准备过程中，第一次用 `git ls-files --others` 的转义输出直接传给 PowerShell `Get-Item` 时，中文视频路径仍是 Git 的引号/八进制转义形式，导致一次 `Cannot find path`。改为直接枚举 `docs` 下的 `.mp4` 后确认文件名与大小；没有移动、删除或改写视频。另一次 `git ls-remote` 因当前受限网络无法解析 `github.com`，因此远端分支是否存在不能在 sandbox 内确认；本地 remote 配置和 tracking 信息正常，上传后以 GitHub 返回结果为准。

`git add` 输出的 LF→CRLF 信息是当前 Windows Git 行尾策略提示，不是 diff check 错误；未为消除提示而批量改写用户文件。

本地实现提交最终创建为 `ac6a9faeef200f0808d8327922c6d2277a231e1a`，主题为 `Build production V2 with isolated Runtime shadow path`。提交审计显示 Author 与 Committer 均为 `KristenYue <yueyt1112@163.com>`，提交正文没有协作者 trailer；提交后工作区为空。该动作只创建本地提交，没有自动 push。

## 85. PR #4 首轮 CI：全量门禁绿色，integration 收集范围失败

维护者把 `production-v2` push 到 GitHub 并创建 PR `#4`。远端作者审计显示 PR 中三个提交都只属于 `KristenYue <yueyt1112@163.com>`。Actions run `38761317922` 的 `test-and-release-check` 全部绿色：项目安装、依赖一致性、普通回归、RAG 门禁、安全故障注入、release-readiness 和 wheel 检查均通过。

`postgres-redis-integration` 的 service containers 初始化、固定 Runtime shadow 依赖安装、全部 migration 与项目 bootstrap 也成功；失败发生在最终 pytest 收集阶段，尚未执行测试函数。命令 `python -m pytest -q -m integration` 会先收集整个 `tests/`，然后才按 marker deselect。该 job 为缩小依赖只安装 `production,shadow,dev`，没有 Gradio，因此收集普通 `tests/test_gradio_app.py` 时出现 `ModuleNotFoundError: No module named 'gradio'`，最终为 `160 deselected, 1 collection error`。

该红色结果不是 PostgreSQL、Redis、migration、Runtime 包或 shadow SQL 失败。修复为把 CI 入口收窄到 `python -m pytest -q tests/integration -m integration`，从根源上不收集普通 Demo 测试；没有为了掩盖范围错误而给数据库 job 安装无关的 Gradio。新增静态契约测试同时断言正确入口存在、旧的全目录入口不存在。旧 run 保留作为问题发现证据，修复提交 push 后以新 run 判断 P1 是否闭环。

本地验证中，部署契约测试为 `5 passed, 1 warning in 0.07s`；新入口的 `--collect-only` 只收集 `tests/integration/test_v2_postgres_redis.py` 中的 2 个 integration 测试，不再触碰 Gradio 测试。`compileall` 与 `git diff --check` 通过，项目内 pytest 临时目录在边界确认后清理。

## 86. PR #4 第二轮 CI 全绿，P1 完成（2026-10-16）

维护者 push 修复提交 `bba892c26dda382df8e72b359e7e0eb09a99bd24` 后，PR `#4` 触发 Actions run `38765518361`。远端 head 与本地提交一致，PR 四个提交的作者仍全部为 `KristenYue <yueyt1112@163.com>`。

两项 job 均为 success：

- `test-and-release-check` 用时 3 分 5 秒，项目安装、依赖一致性、普通回归、冻结 RAG、10/10 安全治理、release-readiness 和 wheel 构建/安装全部通过；构建出的 wheel 版本为 `0.2.2.dev0`。
- `postgres-redis-integration` 用时 2 分 28 秒，固定 SHA 的 `agent-runtime-quality-platform` 安装成功，PostgreSQL 16 与 Redis 7 containers 正常；`0001`、`0002`、`0003_shadow_runs.sql` 均实际应用。收窄后的 integration 命令准确执行 2 项测试，结果为 `2 passed in 0.97s`，覆盖真实 Runtime adapter 契约，以及正式结果不变时 `shadow_runs` 的写入与读回。

读取绿色 job 细节时首次 GitHub API 请求出现一次 `TLS handshake timeout`；随后只重试数据库 job 并过滤关键行，成功取得 migration 和 pytest 汇总。另一次读取主 job 因日志包含约 3.5 GB pip cache 恢复进度而被工具截断；job conclusion、各步骤 conclusion、release report 和 wheel 结果仍可独立确认。这里没有把日志读取问题误判为 CI 问题。

P1 现在可以标记为完成：shadow 默认关闭、关闭时零 Runtime 导入、同步启动/运行/超时/sink 故障隔离、输入深拷贝、敏感异常脱敏、独立 PostgreSQL 审计和一键回滚都已有自动化证据。证据边界仍需保持：CI 使用无外部模型费用的图验证 adapter，并未开启真实生产流量，也没有证明线上质量优于 baseline。

阶段路线复核：下一步进入 P2，固定 50–100 条版本化舆情 Runtime 任务集，生成 baseline/candidate 成对报告，并把 Runtime gate 与现有 RAG、安全、release-readiness 组合；FSO 和 Multi-Agent 继续延后。

证据文档更新后的本地复验为 `5 passed, 1 warning in 0.06s`，P1 状态、run ID 与测试数字断言通过，`git diff --check` 通过；pytest 临时目录随后按项目边界清理。

## 87. P2a/P2b：Runtime 五维门禁与 60 条公开合成任务集（2026-10-16）

P2 首先在独立 Runtime Platform 扩展 paired gate：`RunRecord` 新增 `latency_ms` 与 `estimated_cost_usd`，阈值新增最大延迟增量和最大成本增量，失败原因新增 `latency_regression` 与 `cost_regression`。Runtime 本地完整回归为 `54 passed, 2 skipped in 1.28s`；提交 `0cd15fac75354adf3161cac473614cc7f52f66d1` 的 GitHub Actions run `38768074997` 为 success。主项目因此把 shadow 依赖从旧提交更新到该已验证提交，并把 candidate 标识更新为 `agent-runtime-quality-platform@0.6.0.dev0`；项目版本提升为 `0.2.3.dev0`。

Runtime 验证过程中遇到并解决的问题：

1. Runtime 仓库没有自己的 `.venv`，直接用系统 Python 会让验证环境不可复现。改为复用主项目已经固定依赖的虚拟环境，并显式确认导入来源。
2. 从 Runtime 仓库直接执行短脚本时，因为项目采用 `src/` layout，首次出现模块导入失败。修复为只在该核验命令中显式加入 Runtime 的 `src` 路径，没有改包结构或依赖全局安装。
3. 受限 Windows sandbox 中的 pytest 再次出现完成测试后不退出。检查进程树确认遗留父/子进程 PID `27424/18524` 仍持有临时 SQLite 文件；先核对两个进程的完整命令行，确认均属于本次测试，再终止它们并清理项目内临时目录。随后在不受该 sandbox 进程约束的环境复跑得到上述完整绿色结果。

任务集来源审计时发现既有 `data/evaluation/agent_eval_tasks.jsonl` 只有 36 条，未被 Git 跟踪，缺少本阶段所需类别字段，并含历史批注和临时标记。它不满足 50–100 条验收线，也不适合作为公开、可冻结的数据边界，因此没有复制或包装该文件。新建 `examples/runtime_eval_tasks_v1.jsonl`，只使用合成事件与 `.invalid`/placeholder 敏感样例，共 60 条，覆盖 standard、ambiguous、sensitive_input、candidate_failure、timeout、contract_violation 六类且每类 10 条。

同时新增严格 Pydantic schema、唯一 case ID 校验、50–100 条数量约束、类别计数校验和数据集 SHA-256 校验。`runtime-opinion-manifest/v1` 固定数据版本、文件哈希、任务总数、类别计数，以及成功率、质量、错误率、延迟和成本五类阈值。release-readiness 已把 JSONL 与 manifest 纳入必需公开文件，并增加 `runtime_task_bundle_gate`；篡改测试通过追加一个换行证明哈希校验会拒绝内容变化。

本小节只标记“版本化任务集已固化”。baseline/candidate 成对执行报告和最终组合门禁尚未实现，不能据此宣称 P2 完成；下一步是用同一份冻结任务同时产出双方记录，再调用 Runtime paired gate 生成机器可读报告。

主项目验证结果：任务集、release-readiness 与部署契约定向测试为 `11 passed, 3 warnings in 5.74s`；完整非集成回归为 `166 passed, 2 deselected, 5 warnings in 12.58s`；`compileall`、`pip check`、manifest SHA/60 行计数与 `git diff --check` 均通过。release-readiness 为 `ready_with_warnings`，全部 error 级检查通过，保留的 warning 仍是尚未选择仓库 LICENSE 和本机没有 Docker。测试 warning 仍来自既有 LangGraph、jieba、Starlette、旧 XGBoost pickle 和 pytest cache 权限，没有用屏蔽 warning 的方式改变结论。pytest 临时目录使用项目内独立路径，验证后按绝对路径边界清理。

## 88. P2b 远端验证：任务集与 Runtime 0.6.0 依赖全绿

第一次收到上传截图时，终端仍位于 `agent-runtime-quality-platform`，`git push` 返回 `Everything up-to-date`。只读核验确认 Runtime 的本地/远端均为 `0cd15fa`，但舆情仓库 `production-v2` 仍比 `origin/production-v2` 领先一个提交。随后给出包含完整绝对路径和分支名的命令，维护者把 `5a84d57f488f5698eadd727de60bc7b30c24e8c0` 正确上传到 PR `#4`。这次误操作没有覆盖或丢失提交，只是推送了已经同步的另一个仓库。

首次在受限环境运行 `git fetch` 和 `gh run list` 时，分别出现 `Could not resolve host: github.com` 与无法连接 `api.github.com`。在获得联网执行许可后重试，确认 Actions run `38769408643` 的 head SHA 精确等于 `5a84d57`，没有用旧绿色 run 替代本次证据。

该 run 两项 job 全绿：`test-and-release-check` 用时 2 分 32 秒，普通回归为 `166 passed, 2 deselected, 3 warnings in 12.48s`，RAG、安全、包含 60 条任务的 release-readiness 和 wheel 检查均通过；`postgres-redis-integration` 用时 2 分 36 秒，安装了固定提交构建出的 `agent-runtime-quality-platform-0.6.0.dev0`，数据库/Redis 生命周期为 `2 passed in 0.54s`。GitHub 另外提示 `actions/checkout@v4`、`actions/setup-python@v5` 的 Node 20 兼容层将在 runner 中迁移到 Node 24，以及 `ubuntu-latest` 将来迁移 Ubuntu 26；它们是托管运行器提示，不是当前测试失败，保留到后续 CI 维护阶段处理。

## 89. P2c：成对 Runtime 报告和组合发布门禁

新增跨仓库评测层，读取同一批 60 个冻结 case 的 baseline/candidate 记录，强制 case ID 集合、类别和数量完全一致，再调用固定 Runtime Platform 的真实 `paired_regression_gate`。阈值直接来自任务 manifest，输出同时保留成功率、质量、错误数、工具调用、延迟和估算成本的 baseline、candidate、总 delta 与六类 category delta。报告输入同时记录任务、baseline、candidate 三份 SHA-256；release-readiness 会重新计算哈希、核对 60 个配对 case、阈值、失败列表和证据限制。主项目版本随该组合门禁提升到 `0.2.4.dev0`。

为避免把校准样例包装成线上结果，报告固定写入 `evaluation_mode=synthetic_contract_fixture`，并明确声明：这些记录不是生产流量；故障场景的 `succeeded=true` 表示候选失败/超时/契约错误被按预期隔离；延迟和成本是校准值，不是 SLA。当前成对报告为 passed：成功率 delta `0`、平均质量 delta `+0.01`、平均错误 delta `0`、平均延迟 delta `+35ms`、平均估算成本 delta `+$0.0004`，均在 manifest 阈值内。

本阶段遇到并解决的问题：

1. 主项目虚拟环境尚未安装刚固定的 Runtime shadow extra。为避免修改全局环境，本地开发验证显式把相邻、已通过 CI 的 Runtime `src` 加入本次命令 `PYTHONPATH`；GitHub 普通 job 则正式安装 `.[demo,training,production,shadow,dev]`，确保 CI 使用远端固定 SHA 而不是相邻目录。
2. 初版把 baseline/candidate JSONL 生成到 `data/evaluation/`，但 `.gitignore` 的 `data/evaluation/*.jsonl` 用于阻止私有评测数据误发布，导致两份文件不会进入提交。发现后没有放宽隐私规则，而是把明确公开合成的记录迁到 `examples/`，删除两份被忽略的生成文件，并同步所有路径和哈希检查。
3. Runtime 的平均值计算会产生 `0.010000000000000009` 这类二进制浮点展示噪声。门禁判断本身正确，但机器可读报告不利于人工审阅；输出层因此递归保留 12 位精度，报告展示为 `0.01` 和 `0.0004`，没有改变 Runtime 的阈值算法。
4. 只验证绿色样例无法证明门禁真的会阻断。新增负向回归，在临时副本中把一个 candidate case 改为失败、质量为 0、错误数为 1；报告正确变为 blocked，并产生 `success_rate_regression` 与 `error_rate_regression`。

最终定向测试为 `14 passed, 3 warnings in 5.88s`，完整非集成回归为 `169 passed, 2 deselected, 5 warnings in 12.41s`；release-readiness 的 `runtime_paired_regression_gate` 显示 `paired_cases=60`、`hashes_match=True`、`failures=[]`。warning 仍是既有 LangGraph、jieba、Starlette、旧 XGBoost pickle 和 pytest cache 权限提示。临时目录按绝对路径核验后清理。当前仅能标记“P2c 本地实现与回归完成”；远端固定依赖安装和组合 CI 仍须由新提交的 Actions 证明后，才能把 P2 全部勾选为完成。

## 90. P2c 首轮 CI：跨平台行尾使文本哈希不一致

维护者上传 `e5c06fdd47df34a7ee8cbdb41b519f81c0ee156f` 后，Actions run `38770944930` 精确对应该 SHA。`postgres-redis-integration` 用时 2 分 27 秒并全绿，说明固定 Runtime 依赖、migration、PostgreSQL/Redis 生命周期没有回归。普通 job 安装和依赖一致性通过，但回归结果为 `2 failed, 167 passed, 2 deselected, 3 warnings in 12.26s`，因此后续 RAG、安全、Runtime gate、release-readiness 和 wheel 步骤被正确阻断，P2 没有被误标为完成。

两个失败来自同一个根因：Windows 生成 baseline/candidate JSONL 时工作区字节为 CRLF，报告记录的是原始字节 SHA-256；Git 在提交/Ubuntu checkout 后把文本规范化为 LF。JSON 内容和 60 对指标完全相同，但 Ubuntu 重新计算出的 baseline/candidate 哈希分别为 `12bf8ffa...`、`2e6c301b...`，与 Windows 报告中的 `96819fc4...`、`a6850077...` 不同，导致报告复现测试和 release-readiness 同时失败。

修复没有关闭哈希检查，也没有忽略 CI 差异。新增 `sha256_utf8_lf_normalized` 模式：先按 UTF-8 读取文本并把 CRLF/CR 统一为 LF，再计算 SHA-256；报告显式记录该模式，release-readiness 同时核对模式和值。fixture 生成器改用二进制写入 UTF-8/LF，减少产生平台差异的机会；另加单测直接创建内容相同的 LF 与 CRLF 文件，并断言规范化哈希相同。这样正文任何字符变化仍会改变哈希，只有平台行尾差异被消除。

修复后定向测试为 `8 passed, 3 warnings in 5.63s`，release-readiness 再次为 `ready_with_warnings`，`paired_cases=60`、`hashes_match=True`、`failures=[]`；完整非集成回归为 `170 passed, 2 deselected, 5 warnings in 12.78s`。原 run `38770944930` 保留为跨平台问题发现证据；只有修复提交的新 run 全绿后才关闭 P2。

提交前复核进一步发现任务 manifest 自身仍使用原始字节哈希：当前工作区碰巧是 LF，但未来 Windows 重新 checkout 后也可能变成 CRLF。为避免只修 baseline/candidate 而留下同类隐患，把规范化哈希函数下沉到 `runtime_tasks`，任务 manifest 同样声明 `hash_mode=sha256_utf8_lf_normalized`，任务 loader、成对报告和 release-readiness 共用一个实现。

第一次把生成、定向测试和 release 检查串在一条命令中时，30 秒工具等待窗口只返回了生成器输出；没有把缺失的测试输出视为成功，而是拆开重跑。该次和后续定向测试留下两个项目内临时目录，release-readiness 将它们计入下一次公开文件集合，使文件数暂时显示为 303。确认绝对路径后删除，再生成的干净报告为 281 个文件、零 prohibited path。最终定向测试为 `15 passed, 3 warnings in 6.88s`，完整非集成回归为 `170 passed, 2 deselected, 5 warnings in 23.18s`；`compileall`、`pip check` 和 `git diff --check` 通过。

## 91. 修复后组合 CI 全绿，P2 正式完成

维护者上传修复提交 `b4bf093f88597805f0fb4cf8d8ab2a7e56394927` 后，Actions run `38842124404` 精确对应该 SHA 并全绿。普通 `test-and-release-check` job 用时 2 分 48 秒：固定 Runtime Platform `0.6.0.dev0` 构建安装成功，回归为 `170 passed, 2 deselected, 3 warnings in 13.40s`；冻结 RAG、安全故障注入、60 对 Runtime regression gate、release-readiness 和 wheel 构建/内容检查全部通过。release-readiness 明确输出 `paired_cases=60; hashes_match=True; failures=[]`。

`postgres-redis-integration` job 用时 2 分 17 秒，固定 Runtime 提交安装成功，migration/bootstrap 与真实 PostgreSQL/Redis 生命周期为 `2 passed in 0.63s`。仍有 Node 20 actions 兼容层和未来 Ubuntu 26 runner 迁移提示，与上一轮相同，不影响本次 conclusion。

由此 P2 的四项验收全部闭环：60 条版本化任务、baseline/candidate 成对报告、Runtime/RAG/安全/release-readiness 组合门禁，以及成功率、质量、错误、延迟、成本边界均有机器可读证据。证据边界保持不变：报告是合成契约校准，不是生产流量或 SLA。下一阶段进入 P3 交付包装，不再继续增加 Runtime 抽象、Multi-Agent 或通信场景。

关闭 P2 的文档校准中，第一次按预期命名运行 `tests/test_v2_documentation.py`，但仓库并不存在该文件，pytest 在测试收集前返回 `file or directory not found`。没有把这次命令当成验证结果；随后用实际存在的 `test_release_readiness.py`、`test_v2_deployment.py` 和路线图内容断言复验，结果为 `9 passed, 3 warnings in 16.41s` 与 `p2-roadmap-doc-ok`。临时目录按绝对路径确认后删除。

## 92. P3a：把既有审计账本变成可读取的任务 Trace 页面（2026-10-16）

P3 首项没有新增执行框架或数据库表。审计确认 `analysis_jobs`、`agent_runs`、`run_checkpoints`、`tool_calls`、`human_reviews` 和 `shadow_runs` 已经保存页面所需事实，真正缺口是稳定的读取模型和展示入口。新增 `GET /v2/jobs/{job_id}/trace`：以 Job 为根，按 attempt 返回正式 Run，并在每个 Run 下按 sequence 返回 checkpoint 与 tool call；人工复核和 Shadow 记录仍作为独立集合，避免把 candidate 冒充正式结果。不存在的 Job 返回 404。

新增 `/trace` 可视化查看器。它展示 Job 状态、执行尝试数、恢复次数、最后更新时间、失败代码/原因、worker、心跳相关运行信息、checkpoint 哈希、工具耗时/状态、人工复核和 Shadow 隔离结果。`manual_required` 明确翻译为“暂停 · 等待人工复核”；`retrying` 显示为“等待恢复重试”。页面没有宣称任意节点暂停或节点级续跑，因为 V2 当前恢复语义仍是输入 checkpoint 重放。Trace 资源同时加入 wheel 必需内容门禁，防止源码可用而发布包漏掉页面。

真实 PostgreSQL/Redis integration 用例扩展为在完成正式执行和写入 Shadow 后调用 `get_trace`，核对 Run ID、`input_replay → completed` checkpoint 顺序、空工具列表和独立 Shadow candidate。内存仓库单测覆盖空 Run 的审计 envelope 与不存在 Job；OpenAPI 契约确认新路径只在 V2 service 启用时出现。

本阶段遇到并解决的问题：

1. 当前 `.venv` 的 dev extra 只包含 pytest，没有 `ruff` 和 `mypy`。对应命令返回 `No module named ruff/mypy`；没有为了制造绿色结果临时改依赖，改用项目已有的 pytest、`compileall`、`node --check` 和 `git diff --check`，并保留 CI 作为跨平台验证入口。
2. 新增 FastAPI `TestClient` 路由调用用例后，当前 Windows sandbox 在测试开始后不退出。它与此前本地异步测试挂起模式一致；终止后删除这条重复 HTTP 用例，保留 service 行为测试、OpenAPI 路径测试和既有 Linux CI HTTP 测试，没有把已打印的绿点当成完整通过。
3. wheel 用例第一次失败在 pytest `tmp_path` setup：sandbox 默认 `%TEMP%` 目录无创建权限，并非断言失败。改用项目内显式 `--basetemp` 重跑得到 `2 passed`，随后核验绝对路径位于项目根目录并清理两个临时目录。
4. 第一次在受限 sandbox 启动 localhost Uvicorn 时端口无法连接。获得本机启动许可后重跑成功；第二个视觉 QA 服务首次因临时文件以点开头、Uvicorn 将模块名解释为相对导入而失败，改为合法模块名后启动。页面使用固定合成 UUID 和合成失败记录，不接触真实业务数据。视觉检查覆盖空状态、恢复中状态、失败原因、checkpoint、展开的 tool call 和 Shadow 侧栏；布局清晰，无需返工。两个服务随后停止，临时 QA 脚本删除。
5. 首次完整非 integration 回归为 `168 passed, 3 failed, 2 deselected`；三项失败均因本地 `.venv` 未安装固定 Runtime shadow 包，发生在 `agent_runtime_platform` import，未进入门禁断言。按 P2 已审计做法，仅在复验命令中把相邻、已通过 CI 的 Runtime `src` 加入 `PYTHONPATH`，完整结果变为 `171 passed, 2 deselected, 5 warnings in 14.45s`。
6. 实际 wheel 构建第一次发现 `.venv` 中名为 `build` 的包没有 `build.__main__`；改用 `pip wheel --no-deps --no-build-isolation`。其 sandbox 内首次执行又因 pip build tracker 无权写默认 `%TEMP%` 失败；在获准的本机环境重跑后成功生成 `opinion_analysis_agent-0.2.5.dev0-py3-none-any.whl`。wheel 内容门禁确认 `passed=True`、`missing=[]`、`forbidden=[]`，证明三个 Trace 静态文件已进入发布包。
7. 发布复核发现 `pyproject.toml` 已到 `0.2.5.dev0`，但包级 `__version__` 仍停在历史 `0.1.0`，FastAPI OpenAPI 版本也硬编码为 `0.1.0/0.2.0`。统一为包版本 `0.2.5.dev0`，API 直接读取该值，并增加测试强制包版本、OpenAPI 版本和项目元数据一致，防止后续发布继续漂移。

项目开发版本随该交付功能提升为 `0.2.5.dev0`。加入版本一致性回归后的最终本地证据：完整普通回归 `172 passed, 2 deselected, 5 warnings in 14.49s`，Job/service 定向测试 `13 passed`，wheel 门禁定向测试 `2 passed`，实际 `0.2.5.dev0` wheel 内容检查通过，JavaScript `node --check`、Python `compileall` 和 `git diff --check` 通过。真实 PostgreSQL/Redis Trace 读回仍需本提交的 CI 证明，因此此处只标记 P3a 本地完成，不提前宣称远端闭环。

## 93. P3a 远端 CI 全绿，Trace 查看链路正式闭环

维护者把提交 `f10f4967961fefef9a41654a04ba09699bcd7f66` 上传到 `production-v2` 后，PR `#4` 触发 Actions run `38850433213`，其 head SHA 与本地提交精确一致。首次在受限环境调用 GitHub API 仍出现 `error connecting to api.github.com`；按既定方式在获准联网环境重试后成功读取，没有使用旧 run 替代本次证据。

两项 job 均为 success：

- `test-and-release-check` 用时 2 分 55 秒，普通回归为 `172 passed, 2 deselected, 3 warnings in 10.91s`；冻结 RAG、安全故障注入、60 对 Runtime regression gate 和 release-readiness 全部通过，其中组合门禁仍为 `paired_cases=60; hashes_match=True; failures=[]`。CI 构建并安装 `opinion_analysis_agent-0.2.5.dev0`，wheel 内容检查为 `passed=True`、`missing=[]`、`forbidden=[]`。
- `postgres-redis-integration` 用时 2 分 44 秒，安装固定 Runtime `0.6.0.dev0`，实际应用 `0001`、`0002`、`0003` migrations，并在 PostgreSQL 16 与 Redis 7 上得到 `2 passed in 0.48s`。扩展后的 lifecycle 测试已真实读取正式 Run、`input_replay → completed` checkpoints 和隔离 Shadow 记录。

托管 runner 仍提示 `actions/checkout@v4`、`actions/setup-python@v5` 的 Node 20 兼容层被强制迁移到 Node 24，以及 `ubuntu-latest` 将于 2026-10-19 起逐步迁移 Ubuntu 26。这些提示未影响本次 conclusion，保留到 P3 的 CI 维护/Compose smoke 阶段处理。

至此 P3a 正式闭环：后端审计读取、可视化页面、发布包内容、本地完整回归以及真实 PostgreSQL/Redis 读回均有证据。下一步进入 P3b，更新最终架构图、API 文档和三分钟演示材料；不扩建 Runtime 内核。

## 94. P3b：统一最终架构、API 契约和三分钟演示口径

P3b 审计发现三类交付漂移：`ARCHITECTURE.md` 仍只画 V1 业务图，无法说明 PostgreSQL/Redis、lease 恢复、Trace 和 Shadow；`V2_WEEK2_JOB_API.md` 仍保留“尚未真实集成、恢复留到下一阶段”的历史结论；三分钟讲稿只讲情感路由，没有把异步 Job、失败关闭、恢复、审计和组合门禁串成招聘方能理解的系统故事。路线图表格也仍把 Trace 页面标为未完成。

处理方式不是覆盖历史事实，而是分层维护：

1. 重写 `ARCHITECTURE.md` 为当前唯一最终拓扑，区分 V1 同步展示和 V2 可恢复路径，并明确 Agent 决策图、Job 状态机、七类 PostgreSQL 审计数据、Shadow 隔离、可观测性、组合 CI 与五项证据边界。
2. 新建 `V2_API.md` 作为当前 API 契约，覆盖启用条件、全部公共端点、幂等提交、状态语义、Trace 排序保证、HTTP 错误处理和认证授权缺口。旧 `V2_WEEK2_JOB_API.md` 保留为历史检查点，并在首行链接当前文档，避免早期记录冒充现状。
3. 重写三分钟讲稿，以“业务 Agent 决策 → Production V2 → Trace/恢复/Shadow → 评测和边界”为时间线。明确在线 V1 Demo 与 V2 CI 不是同一部署证据；现场没有 PostgreSQL/Redis 时展示绿色 CI 和 API 文档，不伪造实时任务。
4. README 顶部从 Week 1/Week 2 进度入口切换到最终架构与当前 API；路线图同步标记 P3a、P3b 状态，并把残余风险从“没有 Trace 页面”改成“Trace 尚未接入认证授权”。
5. 新增 `tests/test_v2_documentation.py`，机器检查 README 是否指向当前文档、API 是否覆盖三条 V2 路径与关键错误、架构是否保留恢复/Shadow 边界、演示是否使用正确指标口径，以及 Week 2 文档是否明确标为历史。

文档测试首轮为 `22 passed, 2 failed`。两项失败均是断言表述过窄：API Markdown 表格把方法和路径放在不同单元格，正文不存在连续字符串 `GET /...`；架构原文是“都不会修改正式 Job”，测试却写成“不能修改正式 Job”。修复为验证路径本身和稳定语义短语，没有为了迎合测试改写正确文档。复验为 `24 passed, 3 warnings in 5.46s`，新文档的相对 Markdown 链接检查零断链，`compileall` 与 `git diff --check` 通过。

本阶段只更新交付材料和防漂移测试，没有修改运行时行为。加入 5 项文档契约后的完整普通回归为 `177 passed, 2 deselected, 5 warnings in 14.24s`；GitHub 文档渲染仍由提交后的 CI 验证，因此当前标记为 P3b 本地完成，不提前宣称远端闭环。

## 95. P3c：完整镜像与八服务 Compose 冒烟门禁（2026-10-16）

P3c 开始前先复核 P3b 提交 `0d381f8`：远端 Actions run `38852670307` 两项 job 均为 success，证明最终架构/API/演示文档没有破坏普通回归或 PostgreSQL/Redis integration。随后审计现有 CI，确认它只在 runner Python 环境安装源码，并用 service containers 测数据库和队列；`Dockerfile.v2` 是否能构建、镜像内静态资源和模型资产是否齐全、八服务启动依赖以及从宿主机到 Worker/Trace/监控的组合链路此前都没有真实执行证据。

新增 `compose-smoke` job：从 `Dockerfile.v2` 构建 API/Worker 共用镜像，启动 PostgreSQL、Redis、migration、bootstrap、API、Worker、Prometheus 和 Grafana，再用仅依赖 Python 标准库的 `scripts/smoke_v2_compose.py` 从宿主机走公共接口。冒烟会核对 V2 readiness、无密钥合成 Job、安全终态、幂等重放、正式 Run、首个 `input_replay` checkpoint、默认关闭 Shadow、Trace 页面、API Prometheus 指标、Prometheus readiness 和 Grafana health。失败时仍输出全部 Compose 状态/日志；最终步骤无条件清理 CI 专用容器与 volume，避免污染后续 runner。端口改用 `18000/19090/13000`，减少与 runner 预装服务冲突。

同时处理此前 Actions 已提示的维护债务：三个 job 固定到 `ubuntu-24.04`，避免 `ubuntu-latest` 将来迁移带来无审计的系统变化；checkout 升到 v5、setup-python 升到 v6，以使用它们面向 Node 24 runner 的版本。测试新增静态交付契约，强制 Compose build/up/smoke/always-cleanup、固定 runner 和 action major version继续存在。

本阶段遇到并处理的问题：

1. 当前 Windows 主机再次确认没有 `docker`/`docker compose` 命令。因此这里只能完成脚本编译、YAML/文本契约与普通回归，不能把本地结果描述为 Compose 已跑通；真正的镜像构建和八服务启动必须等待本提交的 GitHub Actions。
2. 首次代码搜索使用了不存在的 `app/` 目录，`rg` 返回路径错误。根据仓库布局改为 `src/opinion_agent/` 后定位到真实指标名 `opinion_agent_http_requests_total`，没有凭记忆写错误断言。
3. 冒烟不能要求 Job 必然 `completed`：默认没有在线 LLM reviewer，安全设计可能返回 `manual_required`。因此接受 `completed` 或 `manual_required` 两个非失败终态，但仍将 `failed_closed` 视为失败并输出持久化错误；这验证可部署性而不绕过业务治理。
4. CI 首次提交前不宣称 Compose 成功。路线图将 P3c 标为“已实现、等待远端实跑”，只有 Actions 真实构建、启动并完成 HTTP 冒烟后才会勾选完成。
5. 首版 Trace 静态资源检查误用了并不存在的 `trace-app` 标识。直接读取真实 `trace.html` 后，改为检查稳定的表单 ID `trace-form`；没有等到远端镜像构建时才发现错误。
6. 完整 pytest 在当前 Windows PTY 中两次停在无摘要状态。逐文件执行定位到既有 `tests/test_api.py` 的第三个 `TestClient` 用例后不退出，与第 92 节记录的本地异步测试驱动器问题一致；P3c 没有修改应用路由。中止时没有把已显示的绿点计作通过，也没有删除该测试或降低 CI 覆盖。改为执行与本阶段直接相关的部署、文档、release-readiness 和 Runtime gate 测试，首次得到 `19 passed, 3 warnings in 6.94s`，最终复验为 `19 passed, 3 warnings in 5.26s`；完整 Linux 回归仍由本提交的 CI 执行。

本地最终证据：`scripts/smoke_v2_compose.py` 通过 `py_compile`；workflow 与 Compose 均可被 YAML 解析；release-readiness 为 `ready_with_warnings`，全部 error 级检查通过，60 对 Runtime 报告继续为 `hashes_match=True`、`failures=[]`；`git diff --check` 通过。保留的两个发布 warning 仍是许可证待版权所有者选择和本机没有 Docker。测试产生的项目内临时目录经绝对路径核验后清理。当前结论仅为“P3c 本地实现与静态/门禁验证完成”，完整八服务实跑仍等待远端 CI。

## 96. P3c 首轮 Compose CI：readiness 依赖键契约不一致

维护者上传提交 `8cd8da70d6245c65e65d8c98b5b0fddecec40b2a` 后，Actions run `38873653908` 精确对应该 head SHA。原有两项 job 均为 success：`test-and-release-check` 完成普通回归、RAG、安全、Runtime、release-readiness 和 wheel；`postgres-redis-integration` 完成 migration/bootstrap 与真实数据库/队列生命周期。新增 `compose-smoke` 成功解析 Compose、用时约 2 分 37 秒构建镜像，并正常启动全部服务，但 HTTP 冒烟等待 240 秒后报 `timed out waiting for V2 API readiness`，因此整个 run 正确标记 failure。

完整容器日志排除了基础设施故障：migration 与 bootstrap 均以 0 退出；PostgreSQL、Redis、API 和 Worker 为 healthy；API 从宿主机持续收到 `/ready` 并返回 200；Prometheus 已 ready，Grafana 也完成启动；失败后的 always 步骤成功输出日志并删除容器和 volume。根因是冒烟脚本把 readiness 的两个稳定键猜成了 `postgres`/`redis`，而 `JobService.readiness()` 的真实公共契约是 `database`/`queue`。由于返回 JSON 始终不满足错误断言，脚本在服务健康时仍持续轮询。

修复以应用源码和既有 `test_v2_jobs.py` 契约为准，把断言改为 `database=True` 与 `queue=True`，并在部署测试中同时强制正确键存在、旧键不得重新出现。没有放宽为“任意 dependencies 值都为 true”，因为那会失去对数据库和队列两个独立探针的语义检查。首轮失败 run 保留为 Compose 门禁实际发现跨层契约错误的证据；只有修复提交的新 run 完整通过后才关闭 P3c。

修复后的部署、Job service 和文档定向回归为 `25 passed, 3 warnings in 6.07s`，smoke 脚本 `py_compile` 与 `git diff --check` 通过；测试临时目录按绝对路径边界清理。

## 97. P3c 第二轮 Compose CI：Grafana 启动期连接重置未被轮询器重试

维护者上传 readiness 修复提交 `1a7e019a315b3235141cd8c0d2502b68edf0c727` 后，Actions run `38878151666` 精确对应本次 head SHA。`test-and-release-check` 用时 3 分 7 秒并全部通过，`postgres-redis-integration` 用时 2 分 26 秒并全部通过。`compose-smoke` 再次成功解析 Compose、构建镜像和启动服务，而且已经越过 V2 API readiness，证明第 96 节的键名修复有效；随后在首次请求 Grafana `/api/health` 时因 `ConnectionResetError: [Errno 104] Connection reset by peer` 失败。always 日志和 volume 清理继续成功。

这是服务启动期间可能出现的连接级瞬态，不是应当放宽的业务契约：Grafana 容器已经启动，但监听端口切换阶段可能接受连接后立即重置。`wait_until` 原来捕获 `HTTPError`、`URLError`、`TimeoutError` 和 JSON `ValueError`，却遗漏了 Python 的 `ConnectionError` 家族，因此没有执行下一次轮询。修复只把 `ConnectionError` 加入可重试集合；`KeyError` 等程序/契约错误仍立即向外传播，避免把真实脚本缺陷等待成超时。

新增两个行为测试：第一次抛 `ConnectionResetError`、第二次成功时必须返回健康结果；`KeyError` 必须立即失败。第二轮失败 run 继续保留，只有第三轮真实 Compose smoke 完整走完 Job、Trace 和监控检查后才关闭 P3c。

修复后的 smoke、部署、Job service 与文档定向测试为 `27 passed, 3 warnings in 7.05s`；脚本编译和 `git diff --check` 通过。清理临时目录后重新生成 release-readiness，结果为 `ready_with_warnings`、288 个公开候选文件、零范围失败，保留 warning 未变。

## 98. P3c 第三轮 Compose CI：HTTP 响应头大小写被普通字典破坏

维护者上传连接瞬态修复提交 `18113c8f0bef0cc9473e8318e4f328834ffba2fa` 后，Actions run `38879428335` 精确对应本次 head SHA。普通 job 用时 2 分 54 秒并全绿，PostgreSQL/Redis integration 用时 2 分 17 秒并全绿。`compose-smoke` 已越过 API、Prometheus 和 Grafana 健康检查，说明前两轮修复都有效；随后报 `first V2 submission did not create a new job`。容器日志却明确显示 `POST /v2/jobs HTTP/1.1` 返回 `202 Accepted`，因此不是 Job 创建失败。

根因位于 smoke HTTP 客户端：HTTP header 名按协议不区分大小写，但 `dict(response.headers.items())` 变成普通大小写敏感字典；Uvicorn 返回小写 `idempotency-replayed`，脚本却查找 `Idempotency-Replayed`，得到空字符串并误判。修复在唯一 HTTP `request` 边界将全部响应头键规范化为小写，创建和重放检查统一读取 `idempotency-replayed`，仍严格要求首个请求为 `false`、重放为 `true`。错误消息同时加入 status 和实际 replay 值，下一次失败可直接区分状态码与响应头问题。

新增 header 规范化行为测试，混合大小写输入必须得到全小写、值不变的结果；部署契约测试强制只使用小写查询。没有删除幂等 header 检查，也没有仅凭 202 就宣称幂等成立。第三轮失败继续作为 HTTP 协议边界问题的发现证据。

修复后的 smoke、部署、Job service 与文档定向测试为 `28 passed, 3 warnings in 5.80s`；脚本编译和 `git diff --check` 通过，临时目录已按边界清理。

## 99. P3c 第四轮 Compose CI 全绿，完整交付链路正式闭环

维护者上传响应头修复提交 `e9db16072639d6678979df3a11b4635f52843b2f` 后，Actions run `38899760131` 精确对应该 head SHA，三个 job 全部 success：

- `test-and-release-check` 用时 2 分 39 秒，普通回归为 `181 passed, 2 deselected, 3 warnings in 8.14s`；冻结 RAG、安全治理、60 对 Runtime gate、release-readiness 与 wheel 均通过，其中组合门禁仍为 `paired_cases=60; hashes_match=True; failures=[]`。
- `postgres-redis-integration` 用时 2 分 20 秒，migration/bootstrap 成功，真实 PostgreSQL/Redis 生命周期为 `2 passed in 0.44s`。
- `compose-smoke` 用时 2 分 51 秒：Compose 配置解析、`Dockerfile.v2` 镜像构建、八服务启动、宿主机 HTTP 冒烟、日志输出和临时 volume 清理全部通过。机器可读摘要为 `passed=true`、`job_status=completed`、`attempt_count=1`、`checkpoint_kinds=[input_replay, completed]`、`idempotent_replay=true`、`shadow_default_off=true`、`database=true`、`queue=true`、`grafana_database=ok`。API 日志同时证明两次 `POST /v2/jobs` 为 202，Job 查询、Trace API、Trace 页面和 metrics 均为 200。

前三轮失败分别暴露 readiness 键名、Grafana 启动期连接重置和 HTTP header 大小写语义问题；每一轮都保留失败证据、增加针对性测试，没有通过删除断言或跳过步骤换取绿色结果。第四轮已经真实走完镜像和公共 API，因此 P3c 正式完成。证据边界仍然是：这是 GitHub 托管 Linux runner 上的无密钥合成冒烟，不是当前 Windows 主机实跑，也不是外部模型、真实流量或生产 SLA 证明。

关闭 P3c 时同步清理最终架构、部署、完成计划、路线图和三分钟讲稿中的过时“Compose 尚未验证”表述，并新增文档防漂移测试，强制这些交付入口引用成功 run 且继续声明本机无 Docker。文档/部署/smoke 定向测试为 `15 passed, 1 warning in 0.22s`；release-readiness 继续为 `ready_with_warnings`、288 个公开候选文件、零范围失败，`git diff --check` 通过。唯一需要维护者决策的发布 warning 仍是根许可证；本机 Docker warning 是环境事实，已有远端 Compose 证据但不会被伪装成“本机可用”。

## 100. P3d README 与交付文档收口（2026-10-16）

P3c 闭环后重新从招聘方和维护者入口审计 README，发现功能方向正确，但交付叙事存在四类漂移：顶部“关键结果”混合了实现条目和实验指标，超过原计划的 5 项；项目链路仍指向早期 `agent-reliability-eval`，没有说明新的 Runtime Platform；Docker 段只给出 V1 Gradio 单容器命令，容易被误解为 V2 生产拓扑；底部“冻结状态”把 2026-09-11 的 V1 冻结记录描述成整个 `production-v2` 当前状态。`V2_WEEK1_BASELINE.md` 也仍保留“真实集成待完成”却没有历史提示，单独从搜索结果进入时可能覆盖当前结论。

本次没有删除旧文档或改写历史失败，因为这些内容是工程过程证据。处理方式是：

1. README 顶部固定为 5 项可复现核心证据：事件隔离数据边界、纯自动级联、选择性自动、RAG 专项门禁、Runtime/Compose 闭环；每项同时写明样本口径、限制和证据入口。
2. 项目链路更新为“冻结模型基座 → 本业务应用 → 通用 Runtime Platform”，并明确旧 reliability 仓库只作为早期评测来源。
3. Docker 说明拆分为 V1 面试 Demo 与 V2 八服务 Compose，两条路径不再混称；目录树补入 `src/opinion_agent/v2`、`Dockerfile.v2`、`compose.yaml`、`deploy/` 和 `scripts/`。
4. 将“冻结状态”改为“版本边界”，明确 tag 只冻结 V1；P0–P3 完成后仍剩认证/Project 授权和许可证决策，不虚构“全部完成”。
5. 新增 `docs/README.md`，把当前权威说明、专项证据和历史检查点分层，并规定冲突时以可执行代码与测试为最高优先级；Week 1 文档补上历史横幅。
6. 新增文档防漂移测试，强制 README 恰有 5 行顶部证据、引用成功 Compose run、保留“非生产 SLA”边界、指向 Runtime Platform，并区分 V1/V2 部署和当前/历史文档。

过程中发现测试统计逻辑第一次把 Markdown 分隔行也算进预期，但过滤条件只匹配以 `| ` 开头的表头和数据行，`|---` 不会被计入；预期因此从“表头 + 分隔 + 5 行 = 7”修正为“表头 + 5 行 = 6”。这不是降低要求，而是让断言与实际解析条件一致。

首轮定向验证还暴露两个命令级问题：断言要求精确短语“不是生产 SLA”，而表格中的实际受控措辞是“不代表生产 SLA”；两者含义一致但字符串不同，修复为断言真实公开措辞。随后误把发布脚本写成不存在的 `scripts/release_readiness.py`，Python 在执行任何检查前明确返回文件不存在；该结果不计为发布验证，改用 CI 和仓库实际入口 `scripts/check_release_readiness.py` 重跑。两个问题都记录在此，避免把失败命令隐藏或误报为测试通过。

最终定向验证为 `18 passed in 0.15s`，包含文档、防漂移、V2 部署和 Compose smoke 客户端测试；`git diff --check` 通过。重新生成的 release-readiness 为 `ready_with_warnings`、289 个公开候选文件、全部 error 级检查通过；新增文件仅为文档导航。保留 warning 仍是根许可证待版权所有者决定和本机缺少 Docker，远端 Compose 证据不用于伪装本机环境。

同时复核上一文档闭环提交 `36f30f9c631671c8080e5d5ff54918df0e29b6d3` 的 Actions run `38901378268`，三个 job 最终均为 success：普通测试与全部质量门禁、真实 PostgreSQL/Redis integration、八服务 Compose smoke 都完整通过。该 run 证明第 99 节写入的 P3c 结论在后续文档提交上没有发生回归。

## 101. P3 最终远端验收与方向复核（2026-10-16）

维护者上传 P3d 收口提交 `d57d36442e15e190b7489f934d212fd989371c08` 后，本地 `HEAD` 与 `origin/production-v2` 精确一致，工作树干净。Actions run `38902169253` 精确对应该 SHA，三个 job 最终全部 success：

- `compose-smoke` 用时 2 分 31 秒，八服务镜像/拓扑启动与公共 API 冒烟完成；机器摘要为 `passed=true`、`job_status=completed`、`attempt_count=1`、`checkpoint_kinds=[input_replay, completed]`、`idempotent_replay=true`、`shadow_default_off=true`，数据库、队列和 Grafana 均健康。
- `test-and-release-check` 用时 2 分 36 秒，普通回归为 `185 passed, 2 deselected, 3 warnings in 9.28s`；RAG、安全治理、60 对 Runtime 回归、release-readiness 与 wheel 内容检查全部通过。公开范围为 289 个文件、`failures=[]`。
- `postgres-redis-integration` 用时 3 分 03 秒，migration/bootstrap 与真实数据库/队列生命周期完成，集成测试为 `2 passed in 0.55s`。

阶段规划复核结论：方向没有跑偏。P0 真实 Runtime CI、P1 隔离 Shadow、P2 版本化组合门禁、P3 Trace/架构/API/演示/Compose/README 收口均已按顺序完成；没有用 Multi-Agent、FSO 或新 Runtime 抽象抢占交付闭环。舆情项目现在已从“继续加功能”转为“受控维护与发布决策”阶段。

当前剩余工作分为两类，不能混称为 P3 未完成：

1. 本仓库上线前的安全/法律前置：认证与 Project 级授权尚未实现，Trace/API 不能暴露到非受信网络；根许可证必须由版权所有者确认后才能加入。
2. 原计划中的下一独立场景：可以开始评估通信故障诊断项目，但应保持为独立仓库和独立数据/指标，不把它塞进已经收口的舆情应用，也不以场景扩张替代认证授权。

本节属于已验收提交之后的审计记录。提交本节本身会再次触发 CI，但不会形成“每次为记录 CI 再无穷追加一条记录”的循环；最终外部 run 状态以 GitHub Actions 页面为准，`38902169253` 已是 P3 功能与文档内容的完整绿色证据。

## 102. V2 认证与 Project RBAC（实施中，等待远端验收）（2026-10-16）

维护者授权完成认证/RBAC 与许可证收口后，先审计现有边界：`requested_by` 直接来自请求 JSON；`GET /v2/jobs/{id}` 与 Trace 只按 UUID 读取；数据库只有 `projects` 外键，没有成员关系。因此此前“不能暴露到非受信网络”的结论成立，不能只在 README 写一句网关建议就算完成。

本次实现选择最小、可替换的部署身份适配器，而不伪造企业 SSO：`V2_AUTH_TOKENS_JSON` 仅通过部署 Secret 提供 opaque token→subject 映射，`X-API-Key` 经恒定时间比较映射为 `Principal`。Token 不进入日志、响应、OpenAPI、URL 或 PostgreSQL；没有配置 token map 时，V2 durable API 在启动时失败，而不是退回匿名模式。未来可由 API gateway/OIDC 在边缘验证身份，只要向该边界提供相同 subject，后续 Project 授权语义不变。

新增 migration `0004_project_members.sql`，将 `(project_id, subject)` 绑定为 `owner`、`analyst` 或 `viewer`。bootstrap 把 `V2_PROJECT_CREATED_BY` 设为初始 owner；`owner/analyst` 才能提交 Job，所有角色才能读取所属 Project 的 Job/Trace。服务端在持久化前用 Principal 覆盖客户端 `requested_by`，因此伪造正文不再能污染审计主体。成员变更只经受信 shell 的 `manage_v2_project_member.py` 执行，避免在尚无审批/审计 UI 时再开放高风险 HTTP 管理入口。

Compose 和 CI 同步改为强制提供 token map 与 bootstrap owner。smoke 使用仅限本次 CI 的临时 token，既验证未认证请求会受保护，也验证合法请求中客户端伪造的 `requested_by` 被替换为认证 subject；Trace 页面要求在当前页面输入 Token，并只通过请求头发送，不写 URL 或浏览器历史。

本机验证中，代码编译、认证/角色/迁移/部署/文档/Compose 客户端定向集共 `42 passed, 1 deselected`；release-readiness 为 `ready_with_warnings`、292 个公开候选文件、零 error 级失败。新增 FastAPI `TestClient` API 边界用例在当前受限 Windows 环境启动 AnyIO portal 时卡在 ProactorEventLoop 的内部 socketpair `accept`，faulthandler 堆栈与第 92 节已知本机问题一致，尚未进入路由或授权业务代码；因此不把该条本机命令记为通过，也不删除 API 边界测试。完整 Linux CI、真实 PostgreSQL migration 和 authenticated Compose smoke 是本阶段的最终验收依据。
