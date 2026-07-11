# Agent Evaluation

本项目的 Agent Evaluation 不是只看情感分类准确率，而是评估一次舆情研判 Agent 运行是否可信、可追踪、可复核。

## 评估层次

1. 模型评估：Accuracy、Macro-F1、Negative Recall，用于判断情感模型本身是否可靠。
2. Workflow contract：检查样本 ID、聚合统计、证据引用、轨迹顺序、复核 fallback 是否一致。
3. Failure recovery：验证 LLM 复核超时、解析失败、人工接管等失败路径是否可恢复。
4. Run audit：对单次运行输出结构化审计结果，暴露风险标记和 scorecard。

## 可复核结果与测量口径

### Transformer 情感模型

公开指标汇总见 [`data/evaluation/transformer_sentiment_metrics_summary.json`](../data/evaluation/transformer_sentiment_metrics_summary.json)，训练入口见 [`scripts/train_transformer_sentiment.py`](../scripts/train_transformer_sentiment.py)。

| 模型 | Accuracy | Macro-F1 | Negative Recall |
| --- | ---: | ---: | ---: |
| RoBERTa v1（无类别加权） | 67.1% | 48.9% | 3.6% |
| RoBERTa v2（balanced class weighting） | 83.9% | 79.6% | 60.7% |

口径说明：以上结果来自导出的 legacy/provisional sentiment split，不是最终金标评估集；完整逐样本结果含原始文本，因此公开仓库只保留不含文本的汇总指标。v2 虽显著提高负类召回，但仍存在短文本负面盲区，所以 Agent 继续保留模型分歧复核与人工接管路径。

### Agent 可靠性

- 36 个 Agent 任务 × 8 类 workflow contract，共执行 288 项断言；
- 7 类离线故障注入均进入预期降级或人工接管路径，恢复结果为 7/7；
- 59 项工程测试通过，并由 GitHub Actions CI 作为发布前回归门禁。

对应实现与结果分别见 [`src/opinion_agent/evaluation/agent_contracts.py`](../src/opinion_agent/evaluation/agent_contracts.py)、[`data/evaluation/failure_recovery_metrics.json`](../data/evaluation/failure_recovery_metrics.json) 和 [`tests/`](../tests/)。

## Run Audit 输出

`audit_agent_run` 会输出：

- `contract`：8 项工作流契约检查结果；
- `trajectory`：节点顺序、状态计数、错误节点、总耗时；
- `sentiment`：样本数、分类分布、模型分歧率；
- `evidence`：检索证据和报告引用是否存在；
- `review`：是否触发复核、复核原因、复核状态；
- `errors`：错误类型、节点和 recoverable 数量；
- `risk_flags`：如 `manual_review_required`、`no_retrieval_evidence`、`llm_review_failed`；
- `scorecard`：contract score、tool success rate、证据引用数、总耗时。

## 命令

```bash
python scripts/audit_agent_run.py \
  --request path/to/request.json \
  --result path/to/result.json \
  --output artifacts/audits/run_audit.json
```

## 设计总结

本评估层将模型指标、workflow contract、failure recovery 和单次运行 audit 统一到可解释评估报告中，用于判断 Agent 是否具备证据可追踪、复核状态一致、失败可恢复和风险可见性。
