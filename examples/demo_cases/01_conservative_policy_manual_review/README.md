# 保守策略：高分歧时进入人工复核

## 用途

- 这个案例用于展示默认业务安全策略：当模型分歧很高时进入 manual_required。
- 即使评论看起来不激烈，只要主模型和辅助信号不一致，系统也不会直接给最终结论。
- 自动放行能力由 data/evaluation/agent_mvp_policy_experiment_tfidf_threshold_08.json 证明，不在单条合成 demo 中硬造。

## 关键结果

- review_status: `manual_required`
- risk_flags: `manual_review_required, review_pending, high_model_disagreement`
- contract_passed: `True`
- tool_success_rate: `0.5`

## 文件

- `request.json`: 输入事件和合成评论。
- `result.json`: Agent 原始输出。
- `audit.json`: 单次运行审计结果。
