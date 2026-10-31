# V2 路线校准审计（更新至 2026-10-16）

## 结论

当前方向没有跑偏，但已经到达必须从“继续扩建 Runtime 内核”转向“形成两个项目之间可验证集成”的节点。

最初计划要求：先把舆情 Agent 做成生产级应用，再整合 Runtime 与评测，最后才考虑通信故障诊断。当前顺序与此一致：舆情仓库保留了冻结 V1，并在 `production-v2` 分支完成后端、任务、观测、RAG、安全和部署主体；随后新建 Runtime Platform，补齐异步执行、checkpoint、恢复、人工中断、租约、fencing 和 PostgreSQL backend。

如果下一阶段继续添加新的 Runtime 抽象、Multi-Agent 或更多存储实现，而不接回舆情业务和评测门禁，就会开始偏离原计划。

## 与最初计划逐项对照

| 原计划目标 | 当前证据 | 判断 |
|---|---|---|
| 保留冻结实验，另建 V2 | 舆情仓库存在 `v1.0-frozen-2026-09-11` tag，当前分支为 `production-v2` | 已对齐 |
| 舆情 Agent 作为旗舰项目 | PostgreSQL 审计表、异步 Job API、ARQ/Redis Worker、lease/heartbeat、结构化日志、Prometheus/Grafana、Compose 已实现 | 已对齐 |
| RAG 与安全专项门禁 | 冻结 RAG 评测、安全治理评测和 CI release-readiness 已存在 | 已对齐 |
| Runtime 补并发、checkpoint、暂停恢复 | Runtime Platform 已覆盖异步工具批次、持久化 checkpoint、恢复、`pause_for_review/resume` | 已对齐 |
| Provider 无关和统一 Trace | Planner Protocol、Run/Step/Tool/Error contracts 与舆情薄适配器已存在 | 已对齐 |
| 生产协调和失败恢复 | PostgreSQL backend、连接池、lease heartbeat、幂等上下文、fencing 与 stale-write 拒绝已实现；真实 PostgreSQL CI 已通过 | 已对齐 |
| 接入舆情真实场景 | Runtime adapter 已进入默认关闭的 V2 shadow Worker，正式结果与独立审计存储隔离 | 已对齐 |
| 版本化评测任务与自动门禁 | 60 条版本化 Runtime 任务、成对报告和组合 CI 门禁已通过 | 已对齐；证据为合成契约校准，不是生产 SLA |
| 运行轨迹查看页面 | `/trace` 已读取 PostgreSQL 中的正式 Run、checkpoint、tool call、恢复原因、人工复核和隔离 Shadow | 已对齐；P3a CI 已验证 |
| FSO 与通信场景 | 仅保留来源边界，尚未接入 | 按计划延后，不能现在抢占主线 |

## 当前剩余风险

1. Runtime 成对报告使用公开合成契约 fixture，能证明配对、阈值、阻断和跨平台复现，但不能作为真实生产流量质量、延迟或成本 SLA。
2. 本机没有 Docker，不能声称本机 Compose 实跑；远端 Actions run `38899760131` 已构建镜像、启动完整八服务并完成 Job/Trace/监控冒烟。
3. V2 已接入 API-token 与 Project RBAC；它不是企业 SSO，部署到非受信网络前仍需 TLS、Secret Manager、网关限流与 token 轮换。
4. CI 已固定 `ubuntu-24.04` 并升级到 `actions/checkout@v5`、`actions/setup-python@v6`；剩余发布 warning 是根许可证尚待版权所有者决定。

## 校准后的下一阶段顺序

### P0：先闭合 Runtime 的可复现证据

- [x] 为 Runtime 仓库编写 CI；
- [x] CI 配置 PostgreSQL 16 service，并安装 `.[dev,postgres]`；
- [x] 工作流配置 migration、真实双连接池竞争测试、普通回归和 JUnit 报告；
- [x] 创建可评审的本地初始 commit，并确认唯一作者为维护者本人；
- [x] 创建公开远端仓库并 push，实际触发 Actions；
- [x] PostgreSQL 16 job 真实通过 migration、连接池和双 owner 接管；
- [x] 修复 unit job 的可选依赖隔离并取得完整绿色 run。

P0 已闭环。Actions run `38742915643` 中 unit job 为 `52 passed, 2 deselected`，真实 PostgreSQL job 为 `1 passed`，两项均上传 JUnit。现在可以进入 P1 shadow 边界实现，但不能跳过默认关闭、正式结果隔离和失败不传播测试。

### P1：实现默认关闭的 V2 shadow 路径

#### P1a：进程内安全边界（已完成）

- [x] `JobExecutor` 只有显式注入 `ShadowExecutor` 时才启动 shadow，默认构造路径零调用；
- [x] 正式 `JobExecutor` 仍产生唯一正式结果，shadow 没有正式状态写入口；
- [x] shadow 使用输入深拷贝，candidate 无法修改正式执行所持有的状态；
- [x] shadow 同步启动失败、超时、candidate 异常和 sink 异常均被隔离，不改变正式结果或 Job 状态；
- [x] 覆盖默认关闭、成功隔离、启动失败、运行失败和超时隔离测试。

#### P1b：部署接线与独立持久化（已完成）

- [x] 增加显式环境开关，默认 `false`，关闭开关即为第一回滚手段；
- [x] 新建独立 `shadow_runs` migration/repository，不复用正式 `finish_execution`；
- [x] 仅在开关开启且依赖完整时组装 Runtime candidate 与 PostgreSQL shadow sink；
- [x] 增加 repository、ARQ worker 装配和关闭开关零调用测试；
- [x] 完成真实 PostgreSQL 集成验证后，才把状态推进到“V2 shadow 已验证”。

P1 已闭环。PR `#4` 的 Actions run `38765518361` 中，普通门禁与 PostgreSQL/Redis integration 均为 success；`0003_shadow_runs.sql` 在 PostgreSQL 16 中实际应用，固定 Runtime adapter 与数据库生命周期 2 项测试为 `2 passed in 0.97s`。这里的“已验证”仅指默认关闭、失败隔离、跨仓库 adapter 契约和独立审计持久化，不代表已经开启生产流量 shadow。

### P2：组合门禁和版本化评测

- [x] 固化 60 条公开合成舆情 Runtime 任务 JSONL、schema/version/hash 和类别计数；
- [x] 生成 baseline/candidate 成对报告；
- [x] 把 Runtime gate 与现有 RAG、安全、release-readiness 串成组合门禁；
- [x] 报告中同时保留成功率、质量、错误率、延迟和成本边界。

P2 已闭环。PR `#4` 的 Actions run `38842124404` 精确对应提交 `b4bf093`：普通 job 为 `170 passed, 2 deselected`，60 对 Runtime gate、RAG、安全、release-readiness 与 wheel 均通过；PostgreSQL/Redis integration 为 `2 passed in 0.63s`。前一 run `38770944930` 因 Windows CRLF 与 Linux LF 造成文本原始字节哈希不一致而失败；修复后任务、baseline 与 candidate 统一使用 `sha256_utf8_lf_normalized`，跨平台测试与远端 CI 均已验证。

### P3：交付包装

- [x] 增加一次运行的 Trace/恢复过程查看页；
- [x] 更新架构图、API 文档和 3 分钟演示；
- [x] README 首页只保留 5 项可复现核心证据，并增加当前/历史文档导航。

### 延后事项

FSO adapter、通信故障诊断和任何 Multi-Agent 扩展都放在 P0–P3 完成之后。它们能增加场景广度，但不能替代当前缺失的真实 PostgreSQL、shadow 隔离和组合门禁证据。

## P3 进入条件与验收重点

P0–P2 的进入条件现已满足：真实 PostgreSQL CI、默认关闭 shadow、正式/候选结果隔离、故障不传播、组合质量门禁和工程日志均已有自动化证据。P3 不再扩建 Runtime 内核，重点转为：

1. [x] 增加一次运行的 Trace、暂停、恢复和失败原因查看页（P3a 已通过本地与 CI 验证）；
2. [x] 更新最终架构图、API 文档和三分钟演示（P3b 已完成本地文档与契约校验）；
3. [x] 增加 Docker 镜像构建与完整 Compose smoke test（P3c 已由 Actions run `38899760131` 验证）；
4. [x] 清理过时文档，让 README 首页只保留 5 项可复现的关键指标，并标清 V1/V2 部署边界；
5. 完成上述交付包装后，再评估通信故障诊断扩展。
