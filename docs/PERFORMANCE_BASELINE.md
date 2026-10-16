# 本地性能与路径基线

## 结论

在本机、单进程、并发度 1、TF-IDF 检索且不调用外部 LLM 的条件下，对 3 个公开合成案例各重复 20 次，共完成 60 次测量：

| 指标 | 结果 |
|---|---:|
| 请求墙钟延迟 P50 | 17.017 ms |
| 请求墙钟延迟 P95 | 19.387 ms |
| 请求墙钟延迟均值 | 16.459 ms |
| 情感分类节点 P50 | 13.776 ms |
| 检索节点 P50 | 1.033 ms |
| 失败运行 | 0 / 60 |

评论级路径共 160 条：

| 路径 | 数量 | 比例 |
|---|---:|---:|
| `fast_path` | 20 | 12.5% |
| `qwen_reviewed` | 0 | 0% |
| `manual_required` | 140 | 87.5% |

本次没有配置外部 Reviewer，因此 provider-reported Token 均为 0。大量评论进入 `manual_required` 是 fail-closed 安全降级的预期结果，不能解释为线上人工率，也不能与 Benchmark v1.5 的冻结测试集路径比例混用。

## 协议

```powershell
.\.venv\Scripts\python.exe scripts\measure_agent_performance.py --repeats 20 --warmup 3
```

- 输入：`examples/demo_cases/*/request.json`
- 主分类器：冻结的 legacy XGBoost
- 辅助分类器：SnowNLP
- 检索：TF-IDF 事件卡
- 外部 LLM：关闭
- 并发：1
- 预热：3 次
- 测量：3 个案例 × 20 次

机器可读原始结果：`data/evaluation/performance_baseline_offline.json`。

## 表述边界

- 这是本地串行工程基线，不是生产 QPS 或吞吐测试。
- 合成案例用于性能测量，不用于声称模型准确率。
- Qwen P50/P95、真实 Token 和成本必须在固定模型、固定 Prompt、固定价格日期和真实 API 调用后另行报告。
- 后续线上测量必须至少记录模型名、Prompt 版本、输入/输出 Token、调用次数、重试次数、失败率和计费口径。
