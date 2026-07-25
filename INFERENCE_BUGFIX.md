# 情感推理链路排查报告

日期：2026-07-23

## 结论

未复现“标签映射颠倒导致所有输入判错”。实际发现了一个已存在的部署来源偏差和两个潜在接线问题：

1. 魔搭仓库没有 `transformer_sentiment_v2_weighted` 权重，也没有 Transformer 运行依赖，默认加载的是 `legacy_xgboost`；因此线上模型不是文档中 Accuracy 83.9% 的 RoBERTa。
2. Transformer 适配器曾复用 XGBoost 的激进清洗，删除英文、数字、空格和表情；训练时只对文本做首尾去空白。
3. Transformer 训练使用 `max_length=192`，原部署适配器默认使用 256。

第 2、3 项已在源代码中对齐，并增加 `id2label` 启动校验。第 1 项没有通过“直接上传权重”处理，因为完整对照证明该权重在相同旧测试集上弱于当前线上基线，贸然替换会造成回归。

## 证据

### 实际加载链路

- 魔搭发布仓库：`public-opinion-agent-demo`
- 默认后端：`legacy_xgboost`
- 实际资产：XGBoost、TF-IDF 和 LabelEncoder 三个 joblib 文件
- 发布仓库不存在 RoBERTa 权重；`requirements.txt` 不包含 `torch` 或 `transformers`
- 本地 RoBERTa v2 权重大小：409,106,392 字节
- 权重 SHA-256：`22d3226f8bb2c4cb35e16a0f053e2c42e1dc0b557449999b6a33cfba19dba259`

### 标签映射

模型配置与训练代码一致：

```text
0 = Negative
1 = Neutral
2 = Positive
3 = Unscorable
```

没有发现编号与标签颠倒。适配器现在会在启动时校验这一映射，不一致则直接报错，不再静默推理。

### 12 条固定样本对照

选样规则为冻结旧测试集每个现有标签的前 4 条，不按预测正确与否挑选。该测试集只有 Negative、Neutral、Positive，没有 Unscorable。

| 指标 | 结果 |
|---|---:|
| 样本数 | 12 |
| 离线 RoBERTa 准确率 | 91.67% |
| 修复后部署适配器准确率 | 91.67% |
| 当前魔搭 XGBoost 准确率 | 91.67% |
| 离线与部署 RoBERTa 一致率 | 100% |

这组结果不支持“部署标签映射导致几乎全错”。

### 完整 143 条旧测试集

| 链路 | Accuracy |
|---|---:|
| 当前魔搭 XGBoost | 90.21% |
| 离线 RoBERTa v2 | 83.92% |
| 修复后 RoBERTa 部署适配器 | 83.92% |
| 离线与部署 RoBERTa 一致率 | 100% |

该测试集来自旧标签，不是最终事件隔离金标准；这里只用于同源链路对照，不能作为最终简历指标。

### 明显情绪烟雾测试

| 文本 | RoBERTa v2 | 当前 XGBoost |
|---|---|---|
| 太差了，完全不能接受 | Neutral | Neutral |
| 这个政策让普通人压力更大 | Positive | Negative |
| 支持国家决定 | Positive | Positive |
| 服务很好，非常满意 | Neutral | Positive |
| 转发微博 | Neutral | Neutral |

“太差了”仍被错判，说明明显错误至少部分属于模型泛化/任务定义问题，而不是部署接线问题。根据任务约束，本次不训练、不加数据、不调参。

## 已完成的最小修复

- Transformer 输入改为只去除首尾空白，与训练数据读取逻辑一致。
- Transformer 默认 `max_length` 改为 192，与训练运行一致。
- 启动时严格校验 `id2label`。
- 显式 Transformer 后端的默认权重路径改为 `transformer_sentiment_v2_weighted`，不再误指向 v1。
- 启动日志记录后端、模型路径、名称、长度和标签映射。
- 新增 `scripts/verify_inference.py`，可复现固定样本与完整测试集对照。

## 发布决策

当前不把 RoBERTa v2 上传到魔搭，也不把它设为默认模型，原因是：

- 同源完整测试集 Accuracy 从 90.21% 降到 83.92%；
- 关键明显负面句仍然判错；
- 不能满足“修复后在线明显情绪正确”的验收条件。

魔搭继续使用 XGBoost 研究基线与已有复核门禁，README 不应将其表述为 83.9% RoBERTa。下一阶段应按项目主线，用新事件人工金标准评测候选现成模型和模型路由，而不是继续把这次问题包装成已修复的部署 Bug。

## 复现

```powershell
cd "C:\Users\29007\Documents\AI agent\舆情研判Agent_高质量重建版"
& ".\.venv\Scripts\python.exe" ".\scripts\verify_inference.py"
```

输出报告：`data/evaluation/inference_verification.json`
