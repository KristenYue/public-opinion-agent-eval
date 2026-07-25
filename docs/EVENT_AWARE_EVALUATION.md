# 事件感知路由与跨事件评测

## 当前结论

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

## 可复现协议

1. 事件级切分，单个事件只能属于 train、validation、test 之一。
2. 只在 validation 的 `0.50 / 0.65 / 0.80` 三档中选择阈值。
3. 选择规则：优先 Macro-F1，其次 Accuracy，再其次自动处理率。
4. 阈值锁定后，test 只执行一次。
5. 同时报告 Accuracy、Macro-F1、各类别 Recall、Qwen 路由率、人工介入率、自动处理率、纠错数和有害覆盖数。

执行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_event_aware_cascade.py `
  --split protocol `
  --reviews data\evaluation\new_events_reviews_second_pass.jsonl `
  --output data\evaluation\event_aware_protocol_final_metrics.json
```

原始机器可读结果：

- `data/evaluation/event_aware_protocol_final_metrics.json`
- `data/evaluation/event_aware_protocol_final_metrics.svg`

## 二次复核门禁

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
