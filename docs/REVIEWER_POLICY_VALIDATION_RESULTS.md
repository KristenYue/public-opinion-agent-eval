# Reviewer 冻结门禁独立验证结果

验证日期：2026-07-11
模型：DeepSeek `deepseek-v4-flash`
策略：`high_confidence_disagreement_v1`

## 设计

首轮12条样本用于发现 harmful override 并冻结门禁。本次从剩余 reviewable cases 中确定性抽取24条不重叠样本，验证期间未修改策略。

## Provider 与结构化指标

| 指标 | 结果 |
|---|---:|
| 样本 | 24 |
| 批次 | 10 |
| 批次成功率 | 100% |
| 样本覆盖率 | 100% |
| rationale 覆盖率 | 100% |
| HTTP attempts | 10 |
| Token usage | 13,412 |
| 批次延迟中位数 | 7.02 s |
| 批次延迟 P95 / max | 10.27 s / 10.27 s |

## 策略对比

| 策略 | Accuracy | 相对基线 | Overrides | Corrected | Harmful |
|---|---:|---:|---:|---:|---:|
| XGBoost baseline | 54.2% | — | 0 | 0 | 0 |
| 无条件采用 Reviewer | 75.0% | +20.8 pp | 9 | 6 | 1 |
| 冻结安全门禁 | 58.3% | +4.2 pp | 3 | 1 | 0 |

## 结论

独立小样本支持门禁的预期行为：它牺牲了无条件采用LLM时的一部分准确率收益，但在本次验证中把 harmful override 从1降为0，并保留4.2个百分点的净提升。该结果适合说明安全性—收益权衡，不足以声称生产泛化或统计显著提升。

## 结果摘要

> 在24条不重叠真实 Reviewer 验证样本上，冻结门禁将准确率由54.2%提升至58.3%，3次受控覆盖纠正1条且 harmful override 为0；同时记录10/10批次成功、13.4k Token和7.02秒中位批次延迟。

必须同时保留“小规模验证”边界，不将结果写成线上业务收益。
