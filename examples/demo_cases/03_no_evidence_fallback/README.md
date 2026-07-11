# 证据缺失：no_retrieval_evidence fallback

## 用途

- 这个案例展示 RAG 检索不到可靠证据时的 fallback。
- 这里使用受控 no-evidence retriever 演示系统边界：没有证据时显式暴露 no_retrieval_evidence，而不是编造历史案例。
- 演示重点是 evidence grounding 和 citation integrity。

## 关键结果

- review_status: `manual_required`
- risk_flags: `manual_review_required, review_pending, no_retrieval_evidence, high_model_disagreement`
- contract_passed: `True`
- tool_success_rate: `0.3333`

## 文件

- `request.json`: 输入事件和合成评论。
- `result.json`: Agent 原始输出。
- `audit.json`: 单次运行审计结果。
