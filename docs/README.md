# 文档导航

本页区分“当前权威说明”和“历史检查点”。历史文档保留问题发现与决策过程，不应覆盖当前契约。

## 当前权威说明

| 主题 | 文档 | 用途 |
|---|---|---|
| 系统全景 | [ARCHITECTURE.md](ARCHITECTURE.md) | V1/V2、PostgreSQL/Redis、恢复、Trace 与 Shadow 边界 |
| API 契约 | [V2_API.md](V2_API.md) | Job、幂等、状态、Trace、错误和安全边界 |
| 部署验收 | [V2_DEPLOYMENT.md](V2_DEPLOYMENT.md) | 八服务 Compose、migration、监控与 CI 冒烟 |
| 恢复语义 | [V2_RECOVERY.md](V2_RECOVERY.md) | lease/heartbeat、重试、checkpoint 与失败关闭 |
| 安全治理 | [V2_SECURITY_GOVERNANCE.md](V2_SECURITY_GOVERNANCE.md) | 预算、白名单、脱敏、人工确认和剩余风险 |
| 评测结论 | [BENCHMARK_V1_5_RESULTS.md](BENCHMARK_V1_5_RESULTS.md) | 599 条/12 事件冻结评测与指标解释 |
| 项目状态 | [PROJECT_COMPLETION_PLAN.md](PROJECT_COMPLETION_PLAN.md) | 已完成项、剩余发布决策与不做事项 |
| 路线审计 | [V2_ROADMAP_ALIGNMENT_2026-10-15.md](V2_ROADMAP_ALIGNMENT_2026-10-15.md) | 原计划对照、阶段验收和方向校准 |
| 完整过程 | [V2_ENGINEERING_LOG.md](V2_ENGINEERING_LOG.md) | 所有主要问题、根因、修复与验证证据 |

## 专项证据

- [RAG_EVALUATION_V1.md](RAG_EVALUATION_V1.md)：检索质量、无关证据拒绝和注入污染门禁。
- [AGENT_EVALUATION.md](AGENT_EVALUATION.md)：Agent 工作流和失败恢复评测。
- [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md)：离线性能基线及非生产 QPS 边界。
- [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md)：公开发布范围、安全和资产检查。
- [INTERVIEW_DEMO_SCRIPT.md](INTERVIEW_DEMO_SCRIPT.md)：三分钟可验证演示顺序；不替代技术契约。

## 历史检查点

- [V2_WEEK1_BASELINE.md](V2_WEEK1_BASELINE.md) 与 [V2_WEEK2_JOB_API.md](V2_WEEK2_JOB_API.md) 记录当时尚未完成的实现状态。
- [PROJECT_FREEZE_2026-09-11.md](PROJECT_FREEZE_2026-09-11.md) 只描述冻结 V1，不代表 `production-v2` 当前状态。
- [EVENT_AWARE_EVALUATION.md](EVENT_AWARE_EVALUATION.md) 是 80 条旧评测；当前跨事件结论以 Benchmark v1.5 为准。
- 带日期的变更审查与部署验证文档保留当时证据，不作为当前部署契约。

遇到冲突时，优先级为：可执行代码与测试 → 当前权威说明 → 专项证据 → 历史检查点。任何历史“待完成”表述都只解释当时阶段。
