# 资产清单

## 可复用数据

- `data/raw_private/events/`: 从`PythonProject/weibo_data`**只读复制**的原始微博事件数据。
- 共有32个CSV，其中12个非空评论事件可用于新数据集。
- 原数据含用户字段，不得公开。

## 历史基线

- `artifacts/legacy_baseline/`: 原三分类XGBoost、TF-IDF和LabelEncoder。
- `artifacts/legacy_baseline/manifest.json`: 三个序列化资产的字节数和 SHA-256；发布门禁会逐项核验。
- `data/legacy_split/`: 原571/143训练测试集。
- 原数据有重复与训练/测试泄漏，标签为SnowNLP伪标签，仅能用于历史对照。
- `.joblib` 反序列化可能执行代码，只允许加载仓库内且通过清单校验的资产，不接受用户上传模型。

## 已移出公开版本的词典

旧项目曾携带 BosonNLP 情感分值、HowNet 情感词、停用词和否定词文件，但没有任何运行时代码、评测或测试引用它们，来源记录也不足以证明可再分发。当前版本已删除并通过发布门禁阻止重新加入；它们不属于项目实现或结果依赖。

## 仅供追溯

- `legacy/reference_scripts/XGBoost 模型训练.py`: 旧训练逻辑参考。
- `legacy/reference_scripts/情感标签2_SnowNLP伪标签.py`: 证明历史标签来源，禁止当作人工真值。
- 旧RAG示例因含明文密钥，未复制进本项目。
