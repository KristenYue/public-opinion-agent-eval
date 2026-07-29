# 事件感知路由与跨事件评测

## Benchmark v1.5 当前结论

Benchmark v1.5 将评测规模扩展到 599 条评论、12 个事件，其中最终测试集包含 6 个未见事件、339 条评论。数据按事件切分，validation 只用于选择阈值，test 在阈值锁定后只运行一次。最终阈值仍为 `0.80`。

| 阶段 | Accuracy | Macro-F1 | Negative Recall | 人工介入率 |
|---|---:|---:|---:|---:|
| XGBoost 基线 | 31.27% | 26.17% | 17.36% | — |
| + 分歧路由、高置信 Qwen | 50.44% | 41.14% | 47.92% | 0% |
| + 事件感知路由、上下文 Qwen | 56.05% | 45.13% | 57.64% | 0% |
| + 低置信人工兜底（完整流程） | 73.75% | 62.65% | 75.69% | 21.24% |

选择性自动口径只统计系统自动处理的 78.76% 样本，Accuracy 为 66.67%。纯自动全量 Accuracy 为 56.05%；完整工作流的 73.75% 使用人工标签模拟人工接管，不能称为模型准确率。

Qwen 在冻结测试中修正 85 个 XGBoost 错误，产生 1 次 harmful override。纯自动 Accuracy 的评论级 bootstrap 95% CI 为 50.74%–61.36%。完整协议、分事件结果、修正记录和表述边界见 [Benchmark v1.5 最终结果](BENCHMARK_V1_5_RESULTS.md)。

## Benchmark v1 历史结果

项目采用“验证集选阈值、测试集只评一次”的事件隔离协议。275 条新事件样本已完成第一轮上下文标注；验证集与测试集中的 38 条不确定样本已全部完成独立二次复核，其中 10 条修改了首轮标签。评测真值状态为 `second_pass_adjudicated`。

验证集选择出的 XGBoost 置信阈值为 `0.80`。锁定阈值后，在 2 个未见测试事件、80 条评论上的消融结果如下：

| 阶段 | Accuracy | Macro-F1 | Negative Recall | Qwen 路由率 | 人工介入率 |
|---|---:|---:|---:|---:|---:|
| XGBoost 基线 | 42.50% | 31.33% | 32.35% | — | — |
| + 分歧路由、高置信 Qwen | 56.25% | 42.17% | 50.00% | 61.25% | 0% |
| + 事件感知路由、上下文 Qwen | 58.75% | 43.90% | 55.88% | 90.00% | 0% |
| + 低置信人工兜底（完整流程） | 75.00% | 54.69% | 82.35% | 90.00% | 22.50% |

必须区分三类口径：

- **纯自动全量口径**：Accuracy 58.75%。低置信 Qwen 不交给人时，仍回退为基线结果。
- **选择性自动口径**：只统计系统实际自动放行的 77.50% 样本，Accuracy 67.74%。
- **完整流程口径**：其余 22.50% 由人工兜底，Accuracy 75.00%。这里使用人工标签模拟人工接管后的结果，不能称为“模型准确率”。

本次测试中，Qwen 修正 13 个 XGBoost 错误，没有造成有害覆盖。结果支持“可靠性路由优于单模型硬判”的项目主线，但样本量与事件量仍较小，不代表生产 SLA。

### 不确定性与分事件结果

固定随机种子、按人工标签分层的 2,000 次评论级 bootstrap 给出以下 95% 区间：

| 口径 | Accuracy 点估计 | 95% CI |
|---|---:|---:|
| XGBoost 基线 | 42.50% | 31.25%–52.50% |
| 纯自动全量 | 58.75% | 48.75%–68.75% |
| 选择性自动 | 67.74% | 56.92%–78.95% |
| 完整流程（含人工兜底） | 75.00% | 66.25%–83.75% |

这组区间只描述“当前两个冻结测试事件内，抽到不同评论”的样本不确定性，不是事件聚类区间，也不能外推为生产泛化能力。两个测试事件的完整流程 Accuracy 分别为 85.00% 和 65.00%，说明当前最重要的改进不是继续围绕同一批评论调参，而是增加真正独立的测试事件。

## 通用可复现协议

1. 事件级切分，单个事件只能属于 train、validation、test 之一。
2. 只在 validation 的 `0.50 / 0.65 / 0.80` 三档中选择阈值。
3. 选择规则：优先 Macro-F1，其次 Accuracy，再其次自动处理率。
4. 阈值锁定后，test 只执行一次。
5. 同时报告 Accuracy、Macro-F1、各类别 Recall、Qwen 路由率、人工介入率、自动处理率、纠错数、有害覆盖数、分事件指标和评论级 bootstrap 区间。

v1.5 执行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_event_aware_cascade.py `
  --queue data\evaluation\benchmark_v1_5_queue.jsonl `
  --reviews data\evaluation\benchmark_v1_5_reviews.jsonl `
  --qwen-responses data\evaluation\benchmark_v1_5_qwen_responses.jsonl `
  --split protocol `
  --bootstrap-resamples 2000 `
  --bootstrap-seed 20260729 `
  --output data\evaluation\benchmark_v1_5_final_metrics.json
```

机器可读结果：

- `data/evaluation/benchmark_v1_5_final_metrics.json`（当前 v1.5）
- `data/evaluation/benchmark_v1_5_final_metrics.svg`（当前 v1.5）
- `data/evaluation/event_aware_protocol_final_metrics.json`
- `data/evaluation/event_aware_protocol_final_metrics.svg`

## v1 二次复核门禁

导入器采用失败关闭策略，避免把无效值或不完整复核写成最终真值。当前 38 条已经全部通过标签、置信度、理由、样本 ID 与第一轮标签一致性校验：

```powershell
.\.venv\Scripts\python.exe scripts\import_second_pass_reviews.py `
  --responses "<复核表导出的 JSON 路径>"
```

脚本已生成 `data/evaluation/new_events_reviews_second_pass.jsonl`，并作为正式跨事件评测的 `--reviews` 输入。

## Demo 口径

- 有可用 Qwen Key：展示真实事件上下文复核、置信度门禁和人工兜底。
- 无 Key：预置样例同时展示快速放行、冻结的离线回放和人工兜底，页面明确标识；自由输入不会伪装成在线 Qwen 结果。
- 事件目标与原帖/事件背景分别输入，避免把“评价对象”和“上下文”混为一个字段。
