# Reviewer 安全门禁：2 分钟 Demo

## 演示目的

展示 LLM Reviewer 不是无条件覆盖基线的最终裁判。系统保留每条建议，但只有满足冻结策略的变更才进入 `final_label`。

## 运行

```powershell
.\.venv\Scripts\python.exe scripts\demo_reviewer_gate.py
```

## 两个对照案例

案例一“哈哈哈”：XGBoost 为 Neutral，辅助模型为 Positive，二者存在分歧；Reviewer 以 High confidence 建议 Positive。门禁采用建议，最终标签为 Positive，并记录 `high_confidence_model_disagreement`。

案例二“笑死了”：XGBoost 与辅助模型都为 Neutral，但 Reviewer 以 High confidence 建议 Positive。由于不存在模型分歧，系统拒绝覆盖，仍保留建议用于审计，最终维持正确的 Neutral。

## 设计说明

> 我最初以为把高风险样本交给 LLM 就能提升结果，但真实调用发现无条件覆盖会纠正 2 条、同时改坏 2 条。因此我没有继续堆 Prompt，而是把 Reviewer 当成不可靠外部组件：保留建议，通过置信度和模型分歧门禁决定是否采用，并把 applied、final_label、decision_reason 写入状态和 trace。这个 Demo 展示一次正确采用和一次避免 harmful override。

## 边界

两个案例来自首轮探索集，用于解释机制，不是独立效果证明。效果结论以冻结后的24条不重叠验证为准。
