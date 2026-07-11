# 模型分歧：触发 manual_required

## 用途

- 这个案例展示模型分歧、负面风险或短文本上下文风险如何进入复核队列。
- 系统不会把主模型原始情绪直接当最终结论，而是标记 manual_required。
- 演示重点是解释 uncertainty-aware routing，而不是声称模型永远正确。

## 关键结果

- review_status: `manual_required`
- risk_flags: `manual_review_required, review_pending, high_model_disagreement`
- contract_passed: `True`
- tool_success_rate: `0.5`

## 文件

- `request.json`: 输入事件和合成评论。
- `result.json`: Agent 原始输出。
- `audit.json`: 单次运行审计结果。
