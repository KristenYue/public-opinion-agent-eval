# V2 路线校准审计（2026-10-15）

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
| 生产协调和失败恢复 | PostgreSQL backend、连接池、lease heartbeat、幂等上下文、fencing 与 stale-write 拒绝已实现 | 已对齐，但真实 PostgreSQL 证据未闭环 |
| 接入舆情真实场景 | 已有真实 LangGraph adapter 集成测试 | 部分完成；尚未进入 V2 shadow Worker |
| 版本化评测任务与自动门禁 | 有 paired gate 单测，但还没有 50–100 条版本化 Runtime JSONL 和组合 CI 报告 | 未完成 |
| 运行轨迹查看页面 | 舆情有 API/观测面板，Runtime 尚无独立 Trace 查看页 | 未完成，非当前最高优先级 |
| FSO 与通信场景 | 仅保留来源边界，尚未接入 | 按计划延后，不能现在抢占主线 |

## 本阶段发现的真实风险

1. Runtime 的真实 PostgreSQL 双连接池竞争测试已经编写，但本机无专用 DSN，所以当前结果仍是 skipped；fake SQL/pool 测试不能替代真实数据库证据。
2. V2 `JobExecutor` 仍是正式结果唯一执行路径，Runtime adapter 没有 shadow runner、默认关闭开关或回滚记录。
3. Runtime 项目当前 `main` 尚无初始 commit，全部文件仍是 untracked。代码可以测试，但还不是可评审、可回滚、可在 CI 中稳定复现的仓库状态。是否创建提交应由维护者明确决定，自动化过程不擅自提交。
4. Runtime 的 paired gate 目前主要是代码级能力，没有版本化真实任务集、基线结果和 candidate 报告。

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

#### P1b：部署接线与独立持久化（下一步）

- [x] 增加显式环境开关，默认 `false`，关闭开关即为第一回滚手段；
- [x] 新建独立 `shadow_runs` migration/repository，不复用正式 `finish_execution`；
- [x] 仅在开关开启且依赖完整时组装 Runtime candidate 与 PostgreSQL shadow sink；
- [x] 增加 repository、ARQ worker 装配和关闭开关零调用测试；
- [x] 完成真实 PostgreSQL 集成验证后，才把状态推进到“V2 shadow 已验证”。

P1 已闭环。PR `#4` 的 Actions run `38765518361` 中，普通门禁与 PostgreSQL/Redis integration 均为 success；`0003_shadow_runs.sql` 在 PostgreSQL 16 中实际应用，固定 Runtime adapter 与数据库生命周期 2 项测试为 `2 passed in 0.97s`。这里的“已验证”仅指默认关闭、失败隔离、跨仓库 adapter 契约和独立审计持久化，不代表已经开启生产流量 shadow。

### P2：组合门禁和版本化评测

- 固化舆情 Runtime 任务 JSONL、schema/version/hash；
- 生成 baseline/candidate 成对报告；
- 把 Runtime gate 与现有 RAG、安全、release-readiness 串成组合门禁；
- 报告中同时保留成功率、质量、错误率、延迟和成本边界。

### P3：交付包装

- 增加一次运行的 Trace/恢复过程查看页；
- 更新架构图、API 文档和 3 分钟演示；
- README 首页只保留可复现指标。

### 延后事项

FSO adapter、通信故障诊断和任何 Multi-Agent 扩展都放在 P0–P3 完成之后。它们能增加场景广度，但不能替代当前缺失的真实 PostgreSQL、shadow 隔离和组合门禁证据。

## 下一阶段验收线

只有同时满足以下条件，才允许把状态从“Runtime 独立验证”推进到“V2 shadow 已验证”：

1. Runtime CI 中真实 PostgreSQL 测试通过；
2. shadow 默认关闭且有一键回滚；
3. shadow 结果与正式 Job result 存储边界明确；
4. shadow 故障不会改变正式状态或返回值；
5. 舆情旧测试、Runtime 测试、RAG、安全和 release gate 全部通过；
6. 工程日志保留问题、修复、测试环境和未验证边界。
