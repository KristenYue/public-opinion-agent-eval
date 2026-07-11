# 资产清单

## 可复用数据

- `data/raw_private/events/`: 从`PythonProject/weibo_data`**只读复制**的原始微博事件数据。
- 共有32个CSV，其中12个非空评论事件可用于新数据集。
- 原数据含用户字段，不得公开。

## 历史基线

- `artifacts/legacy_baseline/`: 原三分类XGBoost、TF-IDF和LabelEncoder。
- `data/legacy_split/`: 原571/143训练测试集。
- 原数据有重复与训练/测试泄漏，标签为SnowNLP伪标签，仅能用于历史对照。

## 词典

- `dictionaries/hownet/`: HowNet正负面词。
- `dictionaries/BosonNLP_sentiment_score.txt`: 带强度分值词典。
- `dictionaries/否定词_融合版.txt`: 否定词。
- 词典目前不声称已与XGBoost特征融合。

## 仅供追溯

- `legacy/reference_scripts/XGBoost 模型训练.py`: 旧训练逻辑参考。
- `legacy/reference_scripts/情感标签2_SnowNLP伪标签.py`: 证明历史标签来源，禁止当作人工真值。
- 旧RAG示例因含明文密钥，未复制进本项目。
