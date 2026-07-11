# Transformer Sentiment v1 Experiment

## Purpose

This run validates that a Chinese Transformer sentiment classifier can be trained,
saved, loaded, and routed through the same Agent sentiment contract as the legacy
XGBoost baseline.

It is an engineering milestone, not a final model-quality claim.

## Run

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe scripts\train_transformer_sentiment.py `
  --epochs 1 `
  --batch-size 8 `
  --model-name-or-path hfl/chinese-roberta-wwm-ext `
  --output-dir artifacts\transformer_sentiment_v1
```

The initial run required `accelerate>=1.1.0` for the installed Transformers
Trainer API. The training script now handles both the older `tokenizer` Trainer
argument and the newer `processing_class` argument.

## Dataset

Source: `data/modeling/transformer_sentiment/*.jsonl`

Counts:

| Split | Rows |
|---|---:|
| train | 456 |
| validation | 115 |
| test | 143 |

Label distribution remains imbalanced, especially for the risk-critical
Negative class. The dataset is exported from legacy/provisional labels and is
not the final gold-standard evaluation set.

## Test Metrics

Path: `artifacts/transformer_sentiment_v1/test_metrics.json`

| Metric | Value |
|---|---:|
| Accuracy | 0.6713 |
| Macro-F1 | 0.4890 |
| Negative recall | 0.0357 |

Negative recall is too low for a risk-review system. This model should not be
used as the trusted production classifier or as release evidence of better risk
detection.

## Current Interpretation

The useful result is architectural:

- the project can fine-tune a Transformer classifier locally;
- the saved artifact loads through `TransformerSentimentClassifier`;
- `SENTIMENT_BACKEND=transformer` can route the API to the new model;
- LangGraph sentiment outputs preserve the classifier `model_name` as `source`.

The model-quality result is not yet acceptable:

- the model over-predicts Positive;
- it misses almost all Negative test cases;
- a manual smoke input, `这个政策让普通人压力更大`, was predicted as Positive.

## Next Fixes

1. Rebuild the Transformer dataset from event-level partially adjudicated JSONL.
2. Keep provisional and second-pass adjudicated labels separated in reports.
3. Compare Transformer, XGBoost, and SnowNLP on the same repaired split.

## Weighted v2 Follow-up

The training script now supports:

```powershell
.\.venv\Scripts\python.exe scripts\train_transformer_sentiment.py `
  --epochs 2 `
  --batch-size 8 `
  --class-weighting balanced `
  --model-name-or-path hfl/chinese-roberta-wwm-ext `
  --output-dir artifacts\transformer_sentiment_v2_weighted
```

Path: `artifacts/transformer_sentiment_v2_weighted/test_metrics.json`

| Metric | v1 unweighted | v2 weighted |
|---|---:|---:|
| Accuracy | 0.6713 | 0.8392 |
| Macro-F1 | 0.4890 | 0.7961 |
| Negative recall | 0.0357 | 0.6071 |

The weighted run is a better candidate for Agent integration because it aligns
with the risk-review goal: missing Negative cases is more harmful than lowering
generic accuracy. Still, the same data limitation applies: final claims must be
re-run on repaired event-level adjudicated evaluation data.

Manual smoke tests still show important blind spots:

| Text | v2 prediction |
|---|---|
| `太差了，完全不能接受` | Neutral |
| `这个政策让普通人压力更大` | Positive |
| `支持国家决定` | Positive |
| `转发微博` | Neutral |

This supports the Agent design choice: the primary classifier remains a signal,
not a final authority. Short or context-dependent samples still need
disagreement checks, LLM review, or manual takeover.
