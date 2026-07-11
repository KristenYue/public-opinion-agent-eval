# Evaluation status

## What is currently measured

The evaluation set contains 242 labeled comments from 12 events. The split is
performed by `event_id`, never by random comment rows:

- train: 8 events / 169 comments
- validation: 2 events / 35 comments
- test: 2 events (`雷军`, `关税`) / 38 comments

The 107 highest-risk comments have completed focused second-pass adjudication, with 24 label
changes. The remaining 135 comments are still `provisional_single_annotator`. This mixed reference
set must not be described as a final gold standard or an inter-annotator agreement study.

## Baseline model results

Held-out test set, four-class evaluation (`Negative`, `Neutral`, `Positive`, `Exclude`):

| Model | Accuracy | Macro-F1 | Negative recall |
|---|---:|---:|---:|
| Legacy XGBoost | 44.7% | 0.312 | 17.6% |
| SnowNLP | 47.4% | 0.347 | 52.9% |

`Unscorable` XGBoost outputs are mapped to the human `Exclude` class. The 38-sample test set is
small, so these estimates have wide uncertainty.

## Agreement-gate result

Across all 242 labeled comments:

- XGBoost and SnowNLP agree on 60 comments (24.8% coverage).
- Accuracy within this automatically accepted subset is 71.7%.
- Disagreement review captures 113 of 130 XGBoost errors (86.9%).
- 182 comments (75.2%) still require review.

Therefore model agreement is an uncertainty signal, not a correctness guarantee. The system never
labels agreement-path predictions as ground truth.

## Agent MVP result

The 242 comments are grouped into 36 disjoint event-level batches:

- required tool execution success: 100%
- structured briefing report success: 100%
- Agent workflow contract success: 100% across 36 tasks and 8 check types
- raw sentiment accuracy: 46.7%
- median local latency: about 50 ms per batch
- p95 local latency: about 83 ms per batch
- evidence acceptance rate after relevance rejection: 19.4%

Every validation batch contains at least one XGBoost error. A batch-level disagreement threshold
therefore cannot reduce review cost while maintaining high error recall. The implemented policy
routes the batch to the review node but sends only selected comment-level risks to the reviewer:
model disagreements, unscorable text and context-dependent comments of at most four characters.

No external LLM reviewer has been evaluated yet. End-to-end corrected accuracy and task-completion
rate are intentionally not reported. All 36 current batches expose `manual_required`, proving the
fallback contract works while also defining the next Agent-specific experiment.

The contract evaluator checks sample identity, aggregate consistency, briefing fields, trajectory
order, trace metadata, disputed-comment references, evidence provenance and review/fallback
consistency. All 288 task-level checks currently pass. This demonstrates internal workflow
consistency, not the correctness of the final business conclusion; label quality, retrieval quality
and external-review quality remain separate evaluation dimensions.

## Agent failure-recovery benchmark

Seven deterministic, offline scenarios exercise the real OpenAI-compatible reviewer boundary and
the complete LangGraph path: transient timeout, 429 rate limit, persistent 503, non-retryable 400,
malformed JSON, unexpected sample ID and input-budget overflow. All seven currently pass their
expected recovery contracts:

- transient timeout and 429 recover on the second attempt with a stable idempotency key;
- persistent 503 stops after the configured three attempts;
- non-retryable 400, payload-contract failures and budget violations do not trigger blind retries;
- terminal failures remain visible as recoverable graph errors, produce `llm_failed`, retain the
  six-node trajectory and include an explicit manual-review action;
- all seven final graph states also pass the eight Agent workflow contract checks.

The benchmark makes no external network call and uses controlled classifier/retriever stubs to
isolate orchestration behavior. It validates recovery semantics, not a live provider SLA or model
quality. The machine-readable report is `data/evaluation/failure_recovery_metrics.json`.

## Reviewer selection benchmark

The provider-independent reviewer benchmark contains all 107 focused-adjudication cases. Current
comment-level policy `multi_signal_v2` produces:

| Item | Result |
|---|---:|
| Selected for LLM review | 89 / 107 (83.2%) |
| XGBoost errors in focused set | 73 |
| Selected XGBoost errors | 62 |
| Error-selection recall | 84.9% |
| Model-disagreement selections | 63 |
| Short-text context selections | 18 |
| Unscorable selections | 8 |

The previous disagreement/unscorable-only selector reviewed 71 comments and captured 56 of the 73
baseline errors (76.7%). Adding short-text context risk reduces missed errors from 17 to 11 at the
cost of 18 additional review items. This is a routing-policy result, not a model-accuracy claim.

The live Reviewer evaluation now uses DeepSeek `deepseek-v4-flash`. The first 12-case smoke run
completed 4/4 structured batches with full item coverage and recorded correction, harmful override,
latency, HTTP attempts and token usage. Its accuracy matched the baseline, so it is evidence that
the integration and measurement path work, not evidence of end-to-end accuracy improvement. A
frozen policy is being evaluated on 24 non-overlapping cases.

## Retrieval sanity benchmark

Twelve manually written event-description queries are used only as a small sanity benchmark:

| Retriever | Recall@1 | MRR@5 |
|---|---:|---:|
| character TF-IDF | 100% | 1.000 |
| BGE-small-zh-v1.5 | 91.7% | 0.958 |
| Hybrid reciprocal-rank fusion | 100% | 1.000 |

The benchmark is keyword-rich and too small for a general retrieval claim. It nevertheless exposed
that replacing lexical retrieval with embeddings does not automatically improve quality. The final
retriever keeps both signals and rejects candidates whose dense similarity is below the provisional
threshold.

## Known data-quality risks

- The 107 comments flagged for adjudication have completed the focused second pass.
- The remaining 135 comments have not received repeat review.
- 236 of 242 existing labels were marked `High` confidence, which suggests annotator
  over-confidence.
- The original provisional file had only 27 notes; all 107 focused-review rows now include a
  written rationale.

These risks are preserved in reports instead of being hidden behind a single accuracy number.

## Adjudication queue history

The focused second-pass review targeted the 107 highest-risk provisional labels. The reproducible
queue is generated by `scripts/build_adjudication_queue.py` and written to:

- `data/evaluation/adjudication_queue.jsonl`
- `data/evaluation/adjudication_summary.json`

Current queue summary:

| Item | Count |
|---|---:|
| Total provisional labels | 242 |
| Adjudication candidates | 107 |
| High priority | 66 |
| Medium priority | 41 |
| Both models disagree with label | 66 |
| Models agree against label | 23 |
| Short text | 51 |
| Low/missing human confidence | 6 |
| Unscorable model output kept as sentiment | 4 |

`high_confidence_without_note` is treated as an explanatory risk attached to already-flagged rows,
not as a standalone reason to expand the queue. This keeps the review batch actionable while still
surfacing where the first-pass annotation needs a written rationale.

## Focused adjudication import

The completed workbook was imported with strict validation. The provisional source file remains
unchanged; accepted decisions are written to `annotations_partially_adjudicated.jsonl` with the
original label and confidence preserved in provenance fields.

Current import status:

| Item | Count |
|---|---:|
| Queue rows | 107 |
| Rows with a second label | 107 |
| Rows with all four editable fields | 107 |
| Strictly valid adjudications | 107 |
| Changed labels | 24 |
| Retained labels | 83 |
| Adjudicated train / validation / test rows | 70 / 20 / 17 |

Changed/not-changed flag conflicts were mechanically corrected from the actual label difference.
All 107 focused responses now pass strict validation and retain their first-pass provenance.

Metrics using the mixed partial-second-pass reference set:

| Model | Test accuracy | Test Macro-F1 |
|---|---:|---:|
| Legacy XGBoost | 44.7% | 0.312 |
| SnowNLP | 47.4% | 0.347 |

The Agent raw sentiment accuracy is 46.7%, while required tool execution remains 100% and evidence
acceptance remains 19.4%. These changes must not be presented as model improvement: model weights
and retrieval configuration are unchanged, and only 17 test rows have completed adjudication.

## Reliability and uncertainty

The deterministic row-level percentile bootstrap uses 5,000 resamples of the 38-comment test set:

| Model | Accuracy 95% interval | Macro-F1 95% interval |
|---|---:|---:|
| Legacy XGBoost | 28.9%–60.5% | 0.182–0.429 |
| SnowNLP | 31.6%–63.2% | 0.223–0.458 |

These intervals are descriptive, not event-generalization guarantees. They resample comment rows
independently, while the test split contains only two events. The wide intervals are evidence that
small point-estimate differences should not drive model-selection claims.

## Reproduction

```powershell
$env:PYTHONPATH="src"
python scripts/evaluate_baselines.py
python scripts/build_adjudication_queue.py
python scripts/apply_adjudication_corrections.py
python scripts/import_adjudication_results.py --responses data/evaluation/adjudication_responses_corrected.jsonl
python scripts/evaluate_baselines.py --source data/evaluation/annotations_partially_adjudicated.jsonl --cases-output data/evaluation/evaluation_cases_partial_adjudication.jsonl --metrics-output data/evaluation/baseline_metrics_partial_adjudication.json
python scripts/build_agent_eval_tasks.py --source data/evaluation/evaluation_cases_partial_adjudication.jsonl --output data/evaluation/agent_eval_tasks_partial_adjudication.jsonl
python scripts/build_agent_eval_tasks.py
$env:HF_HUB_OFFLINE="1"
python scripts/evaluate_agent_mvp.py
python scripts/evaluate_agent_mvp.py --tasks data/evaluation/agent_eval_tasks_partial_adjudication.jsonl --output data/evaluation/agent_mvp_metrics_partial_adjudication.json
python scripts/evaluate_reliability.py
python scripts/evaluate_failure_recovery.py
python scripts/build_reviewer_eval_cases.py
python scripts/evaluate_llm_reviewer.py
python scripts/tune_review_policy.py
```
