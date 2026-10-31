# Evaluation status

## Current benchmark

The current frozen benchmark is **Benchmark v1.5**. It contains 599 context-aware
comment annotations from 12 events. Splits are isolated by `event_id`, never by random
comment rows:

| Split | Events | Comments | Purpose |
|---|---:|---:|---|
| Train | 5 | 225 | Development only |
| Validation | 1 | 35 | Confidence-threshold selection |
| Test | 6 | 339 | One frozen evaluation after threshold lock |

The test distribution is 144 `Negative`, 83 `Neutral`, 95 `Positive`, and 17
`Unscorable`. `Exclude` inputs are normalized to `Unscorable` for evaluation.

All 599 rows received a first-pass annotation with event context. Within validation and
test, all 38 rows flagged as uncertain received an independent second pass; 10 labels
changed and no flagged row remains pending. This does **not** mean every row was labeled
by two annotators. Cohen's Kappa has not been calculated, so the dataset must not be
described as a final gold standard or a production ground truth.

For the complete provenance, privacy boundary, and allowed claims, see `DATA_CARD.md` and
`ANNOTATION_GUIDE.md`.

## Frozen test results

| System | Accuracy | Macro-F1 | Negative recall | Scope |
|---|---:|---:|---:|---|
| Legacy XGBoost | 31.27% | 26.17% | 17.36% | Baseline signal |
| Event-aware fully automatic cascade | 56.05% | 45.13% | 57.64% | All 339 test rows |
| Selective automatic output | 66.67% | 53.22% | 70.09% | 78.76% automatic coverage |
| Complete workflow with simulated human fallback | 73.75% | 62.65% | 75.69% | 21.24% human-label fallback |

The main model-quality number is the **56.05% fully automatic Accuracy**. The 66.67%
number is valid only when reported together with 78.76% coverage. The 73.75% result is an
end-to-end workflow result that includes simulated human takeover and is not model
accuracy or a production SLA.

Threshold `0.80` was selected only on the 35 validation rows and then locked. Human test
labels were not exposed to Qwen during inference. Detailed results and bootstrap intervals
are in `docs/BENCHMARK_V1_5_RESULTS.md` and `docs/EVENT_AWARE_EVALUATION.md`.

## Reviewer diagnostics

The frozen test diagnostics separate Reviewer behavior from the governed workflow:

| Diagnostic | Result |
|---|---:|
| Unconditional Qwen accuracy | 60.77% |
| Unconditional corrections / harmful overrides | 103 / 3 |
| Governed Qwen corrections / harmful overrides | 85 / 1 |
| Governed fast / Qwen / manual paths | 47 / 220 / 72 |
| Governed net corrected errors | 84 |

These are post-hoc diagnostics over existing frozen responses; they make no new provider
calls and do not retune the test set. Confidence-bucket results and definitions are in
`docs/REVIEWER_CONFIDENCE_DIAGNOSTICS.md`.

## Agent contract and failure recovery

The offline contract suite checks sample identity, aggregate consistency, briefing fields,
trajectory order, trace metadata, disputed-comment references, evidence provenance, and
review/fallback consistency. The deterministic failure-recovery benchmark exercises seven
scenarios at the real OpenAI-compatible reviewer boundary: transient timeout, rate limit,
persistent 503, non-retryable 400, malformed JSON, unexpected sample ID, and input-budget
overflow.

All scenarios currently satisfy their expected orchestration and recovery contracts. This
demonstrates deterministic workflow behavior, not a live provider SLA or conclusion
correctness. Machine-readable evidence is stored under `data/evaluation/`.

## Performance baseline

The offline serial baseline contains 60 local runs with no external LLM calls:

| Measure | Result |
|---|---:|
| End-to-end wall time P50 | 17.017 ms |
| End-to-end wall time P95 | 19.387 ms |
| Mean wall time | 16.459 ms |
| Failures | 0 |
| API tokens | 0 |

This is a reproducible local orchestration baseline, not a throughput, concurrency, live
provider latency, or production-capacity claim. See `docs/PERFORMANCE_BASELINE.md`.

## Prompt regression and release gate

The release-readiness check requires the frozen prompt contract, Reviewer diagnostic,
public documentation, ignore rules, synthetic-demo boundaries, machine-readable Agent
evidence, and a credential-pattern scan. Prompt version `event_stance_v2` is compared with
the committed regression baseline before release.

Run the complete local verification with:

```powershell
python scripts/check_prompt_regression.py
python scripts/check_release_readiness.py
python -m pytest -q
```

## Retrieval sanity benchmark

Twelve manually written, keyword-rich event-description queries remain a small sanity
benchmark:

| Retriever | Recall@1 | MRR@5 |
|---|---:|---:|
| Character TF-IDF | 100% | 1.000 |
| BGE-small-zh-v1.5 | 91.7% | 0.958 |
| Hybrid reciprocal-rank fusion | 100% | 1.000 |

The set is too small and too lexical for a general retrieval-quality claim. It only shows
why the implementation retains lexical and dense signals instead of assuming embeddings
are always superior.

## Historical experiments

Earlier project iterations used a 242-comment provisional set, a 38-comment test split,
and a 107-row focused adjudication queue. Those experiments helped establish the review
policy and exposed data-quality risks, but they are superseded for headline performance
claims by Benchmark v1.5. Historical artifacts may remain for traceability and must not be
mixed with current 599-row benchmark numbers.

## Known limitations

- The benchmark is small and covers only 12 events.
- Most rows have one context-aware first-pass annotation, not two independent labels.
- The second pass is risk-targeted, so it cannot support an agreement-rate claim.
- Qwen responses depend on a specific prompt and provider snapshot.
- Offline contract success does not establish production reliability.
- Local serial latency does not establish QPS, concurrency, or live API latency.
- The dataset and evaluation support reproducible evidence and regression testing, not a
  claim of universal public-opinion understanding.
