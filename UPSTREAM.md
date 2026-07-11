# Upstream references and modifications

This repository does not claim authorship of external frameworks or pretrained models.

## LangGraph

- Source: https://github.com/langchain-ai/langgraph
- Reused concept: typed shared state, nodes, reducers and conditional edges.
- Project-specific work: sentiment tools, evidence schema, multi-signal routing, review fallback,
  trace fields and event-level evaluation.

## BGE-small-zh-v1.5

- Source: https://huggingface.co/BAAI/bge-small-zh-v1.5
- Usage: local Chinese dense embeddings for event-card retrieval.
- Project-specific work: sparse/dense comparison, reciprocal-rank fusion, same-event exclusion and
  low-relevance rejection.

## SnowNLP

- Source: https://github.com/isnowfy/snownlp
- Usage: secondary historical sentiment signal.
- It is not treated as ground truth or a calibrated confidence estimator.

## Undergraduate model assets

The XGBoost model, TF-IDF vectorizer and label encoder come from the author's undergraduate thesis.
The new repository adds stable loading, validation, Agent integration and leakage-aware evaluation.
