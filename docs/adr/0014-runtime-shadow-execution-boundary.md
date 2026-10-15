# ADR-0014：Runtime shadow 执行隔离边界

- 状态：Accepted；deployment default disabled
- 日期：2026-10-15

## 决策

V2 正式 `JobExecutor` 继续产生唯一正式状态与结果。可选 `ShadowExecutor` 只在构造时显式注入后运行候选实现；默认值为 `None`，因此现有 Worker 零调用、零额外成本。

Shadow 获得正式输入的深拷贝，不能修改正式 runner 的 state。正式结果先调用 `finish_execution` 或失败记录，再在 `finally` 中等待有界 shadow；候选超时、异常和 sink 异常都只能形成 shadow 记录或结构化日志，不得改变正式返回状态。

## P1a 执行边界

P1a 建立执行与失败隔离：`ShadowRunner`、`ShadowSink`、`ShadowRecord` 和 `ShadowExecutor`。同步启动失败、candidate 异常、超时与 sink 异常都不能改变正式路径。

## P1b 部署接线

P1b 新增独立 `shadow_runs` 表与 `PsycopgShadowSink`。该表通过外键关联正式 run，但 sink 的 SQL 只允许 `INSERT INTO shadow_runs`，不更新 `analysis_jobs` 或 `agent_runs`。同一正式 run 与 candidate 只保留第一条记录，避免队列重复交付覆盖审计证据。

ARQ Worker 通过 `RUNTIME_SHADOW_ENABLED` 装配，缺省或显式 `false` 时不导入 Runtime 包、不创建 adapter，也不增加第二次图执行。开启后使用固定到已验证提交的 Runtime Platform adapter；Runtime 自身 checkpoint 使用独立 SQLite 路径，candidate 最终结果写 PostgreSQL `shadow_runs`。

第一回滚手段是把 `RUNTIME_SHADOW_ENABLED=false` 并重启 Worker。关闭不会删除已有 shadow 审计记录，也不需要回滚正式表结构。启用会产生第二次模型/工具调用及对应成本，只允许先在受控流量验证。

## 必须保持的测试

- 未注入 shadow 时候选零调用；
- shadow 成功只能写独立 sink；
- shadow 异常、超时或 sink 失败不改变正式结果；
- shadow 对输入的修改不影响正式 runner。
- 开关缺省关闭时不得加载可选 Runtime 依赖；
- migration 不得 ALTER 正式 Job/Run 表；
- PostgreSQL sink 只能写 `shadow_runs`；
- 异常消息和结果写入前必须脱敏。
