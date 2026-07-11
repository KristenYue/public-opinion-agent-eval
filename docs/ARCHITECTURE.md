# Current architecture

```text
comments
   |
   v
legacy XGBoost tool + SnowNLP secondary signal
   |
   v
sentiment aggregation
   |
   v
event-card retrieval
  - character TF-IDF
  - BGE-small-zh-v1.5
  - reciprocal-rank fusion
  - relevance rejection
   |
   v
multi-signal review router
  - unscorable text
  - model disagreement
  - short-text context risk
  - no credible retrieval evidence
   |
   +---- no trigger ----> baseline result with limitations
   |
   +---- trigger --------> structured LLM review or explicit manual-review fallback
                               |
                               v
                         opinion briefing composer
                         - attention level
                         - risk signals
                         - disputed comments
                         - evidence references
                         - review status
                         - recommended actions
```

The graph stores raw model outputs, routing reasons, evidence provenance, node latency, degraded
states and recoverable errors. XGBoost confidence is retained for diagnostics but is not used as a
correctness gate because the held-out analysis found no reliable confidence-accuracy relationship.
Both routing branches converge on the briefing composer, so the API returns the same structured
business contract when the LLM succeeds, is unavailable, or fails and requires manual review.
The comment-level reviewer selector uses observable runtime signals only. Policy
`multi_signal_v2` selects unscorable comments, model disagreements and comments with at most four
characters, which are especially dependent on the original-post context supplied through the API.
The external-review boundary adds a stable idempotency key, bounded exponential retries for
timeouts/transport errors/429/5xx, an input-character budget, strict one-result-per-sample ID
validation and provider-reported token usage. Contract violations remain recoverable graph errors
and converge on the manual-review fallback instead of being treated as successful LLM output.

The evaluation layer separately validates eight Agent contracts on every scenario batch: sample
identity, aggregate consistency, briefing schema, trajectory order, trace metadata, disputed-item
references, evidence provenance and review/fallback consistency. These checks are independent of
sentiment accuracy and make orchestration regressions visible in the generated metrics report.

The external-review boundary is also exercised by an offline failure-injection harness. It drives
timeouts, retryable and non-retryable HTTP responses, malformed structured output, sample-ID
violations and input-budget overflow through the complete graph. The harness verifies bounded
retries, stable idempotency keys, recoverable error records, `llm_failed` status and explicit manual
fallback actions without depending on a live provider.
