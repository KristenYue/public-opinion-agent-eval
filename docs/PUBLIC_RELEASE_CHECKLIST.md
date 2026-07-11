# Public Release Checklist

Use this checklist before creating or pushing the public GitHub repository.

## Must Pass

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
```

Current expected state:

- blocking release checks pass;
- warnings may remain for missing Docker/Git runtime or no LICENSE;
- no real API keys are present in source/docs/examples;
- synthetic demo event cards are used for public demo paths.

## Do Not Publish

The public repository must not include:

- `data/raw_private/`
- `data/legacy_split/`
- `data/annotations/`
- `data/evaluation/*.jsonl`
- `data/processed/comments_deduplicated.csv`
- `data/processed/event_cards.jsonl`
- `legacy/`
- `references/`
- `.env`
- Transformer model artifacts such as `model.safetensors`, `optimizer.pt`, checkpoints and `artifacts/transformer_sentiment_*/`

The public metric file for Transformer work is:

- `data/evaluation/transformer_sentiment_metrics_summary.json`

It intentionally excludes sample-level text.

## Positioning

Use:

> 可复核中文舆情风险研判 Agent

Avoid presenting the project as a generic Deep Research agent. The strongest
claim is uncertainty-aware risk review, not broad autonomous research.

## Claims That Are Safe

- Transformer v2 weighted reached 83.9% accuracy, 79.6% Macro-F1 and 60.7%
  Negative Recall on the exported legacy/provisional sentiment split.
- Agent workflow contracts pass across sample identity, evidence provenance,
  routing/fallback and trace consistency.
- Failure recovery is verified with controlled mock reviewer scenarios.
- MCP, FastAPI and console entrypoints reuse the same LangGraph workflow.

## Claims To Avoid

- Do not call the evaluation data a final gold standard.
- Do not claim real LLM reviewer correction quality until a live provider run is completed.
- Do not claim production-ready risk detection from Transformer metrics alone.
- Do not imply evidence retrieval proves causal relationships.

## Suggested GitHub Steps

1. Initialize a Git repository only after the ignore rules are confirmed.
2. Inspect the staged file list before the first commit.
3. Confirm no large model files or private data are staged.
4. Commit code, public docs, synthetic examples and machine-readable summaries.
5. Add a clear README section for local demo, MCP server, metrics and limitations.

