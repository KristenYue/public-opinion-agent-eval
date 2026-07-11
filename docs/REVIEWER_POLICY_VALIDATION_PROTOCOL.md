# Reviewer 门禁独立验证协议

冻结日期：2026-07-11

## 冻结策略

策略名：`high_confidence_disagreement_v1`

只有同时满足以下条件时才采用 Reviewer 标签：

1. Reviewer 标签与 XGBoost 基线不同；
2. Reviewer confidence 为 `High`；
3. 主模型与辅助模型存在分歧（`models_agree == false`）。

其他 LLM 建议保留用于审计，但不覆盖基线。独立验证结束前不再调整阈值或规则。

## 验证集

- 从尚未进入首轮 12 条实验的 reviewable cases 中确定性、按 selection reason 轮询抽取 24 条；
- 使用 `--exclude-responses data/evaluation/llm_reviewer_responses.jsonl` 保证样本不重叠；
- 结果写入独立的 `llm_reviewer_validation_*` 文件，保留首轮探索证据。

## 主要指标

1. gated final accuracy 与 baseline accuracy；
2. harmful override 数量；
3. corrected error 数量；
4. override rate；
5. structured batch success、coverage、latency 和 token usage。

## 判读边界

24 条仍属于小规模作品集验证，不声称生产泛化能力。若门禁未提升准确率，也保留原始结果并分析失败模式，不继续在同一验证集上调规则。
