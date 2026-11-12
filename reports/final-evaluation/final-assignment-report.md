# The Relay — Final Assignment Report

Date: 2026-11-12. Two-page draft; personal sections require confirmation. Measurements below come from preserved project records, not new model calls.

## 1. What I built and why

The Relay is a Python terminal research assistant grounded in three version-pinned papers. Its flow is question classification → Groq tool planning → local retrieval → bounded evidence → validated streaming → completion checks. It includes help/refusal/failure branches, a bounded tool-call loop, and repeated terminal questions. Citations carry authoritative paper/version/page metadata. Phase 5.4 uses prompt `relay-phase3-v3`, evidence-first quotations, deterministic multipart coverage, strict JSON completion, and optional redacted failure diagnostics. Coverage checks quantities against each claim's own quotations; they do not prove unrestricted semantic entailment.

## 2. The real service and my stand-in

Real integration uses Groq `openai/gpt-oss-20b`, structured tool calls, and streaming. The FastAPI stand-in models completion/SSE responses, bounded queues, overload, transient failures, rate limits, and daily request/token budgets. Its delays and token estimates are simulated. The in-process request manager bounds concurrency and retries; it is not a distributed queue. The live CLI does not automatically retry failed generation.

## 3. Results

Recorded latency percentiles are reproduced unchanged below; **n** is the measurement count. Calibration comprised 10 real requests: 3 non-streaming, 3 streaming, 3 concurrent non-streaming successes, and one deliberate invalid-model error.

| Dataset | TTFT p50 / p95 / p99, ms (n) | Total p50 / p95 / p99, ms (n) | Failed / given up |
|---|---|---|---|
| Real Groq calibration | 757.566 / 1511.044 / 1578.020 (3) | 466.627 / 1265.984 / 1531.804 (9 successes) | 1 / 10, deliberate probe |
| Simulated steady | 829.065 / 850.627 / 857.245 (40) | 829.239 / 850.777 / 857.437 (40) | 0 / 40 |
| Simulated burst | 817.115 / 842.938 / 845.627 (30) | 1643.186 / 3244.761 / 3246.141 (30) | 0 / 30 |
| Simulated overload | 387.041 / 651.615 / 658.333 (25) | 307.889 / 633.399 / 654.101 (80) | 55 / 80: 35 timeouts, 20 errors |

Stand-in TTFT is the harness-observed value: HTTPX ASGI transport buffers the response, so it is **not wire-level first-token latency**. Stand-in total percentiles include fast failures; real calibration totals exclude its error probe. These datasets are not pooled. Real capacity under load and real 429 latency percentiles: **Not measured**; quota was not deliberately exhausted. No new end-to-end percentile is calculated from incomplete/mixed evaluation runs.

**Quality:** original Phase 5 used a controlled 20-question protocol, prompt v1, BM25/600, top-4, a 3000-token evidence ceiling, temperature/seed 0. Grades remain **5 correct answerable answers + 8 correct refusals + 7 operational failures = 13/20 graded, 7/20 ungraded**. A1/A3/A5/A6/A7 are correct; U1–U8 are refused correctly. A2/A4/A8–A12 stay blank, never wrong/refused wrongly. Five failures were citation validation; two were stream format.

**Tokens per successful Phase 5 answer (input/output, planning plus generation):** A1 `3063/328`; A3 `2804/161`; A5 `3692/273`; A6 `3899/157`; A7 `3488/275`. Full failed-turn usage: **Not measured**, because interrupted requests lack final usage. Phase 4 CSV grades are blank because that experiment did not assess answer quality.

**Separate follow-ups:** Phase 5.1 diagnosed the failures; Phase 5.2 added quote-format handling/diagnostics and prompt v2. Phase 5.3 answered A2 with a valid citation (now factually verified), failed A4 with `stream_format`, hit HTTP 429 on A8, and never attempted A9–A12. Phase 5.4 adds local reliability safeguards, not a new controlled quality score. Later November 12 manual sessions reported fuller BLEU/routing answers; this is observed behavior, not statistically proven improvement. XWinograd's definition answer did not test accuracy. Broad “Attention” was refused. Original grades remain unchanged.

## 4. Where time goes

Phase 5 A1 spent `10617.764 ms` in retrieval out of `12879.494 ms` total. Warm A3 spent `105.202 ms` retrieving, `338.305 ms` planning, `377.046 ms` generating, and `0.706 ms` validating. Phase 5.3 A2 retrieval was `40416.505 ms` of `42275.984 ms`. Simulated burst queue wait p95 was `2406.0 ms`. Cold initialization, generation, and queueing dominate different cases; isolated network/provider-compute timings were **Not measured**.

## 5. When limits are hit

Phase 4's simulated minute limit admitted `30/40` requests; halving it admitted `15/40`. A simulated daily budget admitted `10/25`. These are not Groq quotas. Real Phase 5 first attempts U2/U3/U5 hit rate limits and completed after one retry each: 23 question attempts for 20 questions. Phase 5.3 stopped on A8's HTTP 429 with `Retry-After: 11`, leaving four questions unattempted.

## 6. Retries

One simulated transient failure recovered with one retry. Retrying an exhausted minute made things worse: successes stayed `3/6`, while retries added **six extra attempts**. Daily-budget exhaustion was non-retryable (`3/5` succeeded). Final review corrected a policy defect that let a cap or negative jitter shorten `Retry-After`; the server minimum now survives both. Historical measurements were not rerun or replaced.

## 7. Retrieval quality versus cost

The offline comparison contains 60 rows: 20 questions × three strategies, preset 600/50, top-4, ranking depth 50, 3000-token ceiling. Coverage/MRR/rank/context means use 12 answerable questions; latency means use all 20 per strategy after warmup.

| Method | Complete coverage | MRR | Mean first relevant rank | Context tokens | Retrieval ms |
|---|---:|---:|---:|---:|---:|
| Vector | 9/12 | 0.6566 | 3.667 | 1790.417 | 64.118 |
| BM25 | 11/12 | 0.7292 | 1.667 | 1839.000 | 125.090 |
| Hybrid | 10/12 | 0.7778 | 1.833 | 1919.083 | 150.977 |

Select the existing **BM25/600/top-4** configuration for its best coverage and mean first relevant rank. Hybrid leads MRR at higher context/latency cost; vector is fastest. Each evidence gate flagged `6/8` unsupported questions, with no answerable false refusals; U2/U6 needed model-level refusal. This diagnostic set measures annotated evidence coverage, not held-out answer accuracy.

## 8. Three ways retrieval can mislead

1. U8 asks for H-Net WMT BLEU; vector rank 1 is Attention p. 8. Substituting its `28.4` would misattribute another model's result.
2. A6's top-4 comparison covers only one of two annotated units for every method: training-token evidence can hide the missing parameter statement, even while the gate passes.
3. U6 asks for carbon footprint; BM25 rank 1 supplies Attention p. 8 training hardware/FLOPs, and the gate passes. Those figures do not establish carbon emissions; the model ultimately refused.

Local PDF review also preserves two source conflicts: Attention p. 8 EN-FR `41.8` in Table 2 versus `41.0` in prose; H-Net p. 17 Figure 6 says `3.6× less data`, while nearby prose says `3.6× the amount`. Latest routing initialization/threshold match p. 6, but its exact generated formula is unavailable. Earlier A8's full answer/citations are also unavailable; neither answer is fully verified.

## 9. Vaani feedback

[Add actual Vaani feedback if received; otherwise state that no feedback was received.]

## 10. How I worked with the assistant

Repository records show AI-assisted implementation, review, diagnosis, and tests. Three actual prompt strategies in the supplied history were evidence-only grading, read-only diagnosis before edits, and deterministic coverage with exact quotations. One documented mistake was assuming JSON objects always had newline separators; real adjacent objects exposed it, and the parser was changed. An extra repair-retry approach proposed in Phase 5.1 was not adopted in Phase 5.4; validation and coverage were improved instead. **[Confirm your personal role in that decision/rejection.]**

The supplied history confirms that the user set constraints, prescribed grades, and supplied manual terminal observations. **[Add which technical decisions, implementation, tests, and PDF verification you personally performed; do not claim assistant work as your own.]** No personal contribution or feedback is inferred.

Evidence: [Phase 4 measurements](../phase4/completion-status.md), [Phase 5 results](answer-quality-results.json), [manual grades](manual-grading.csv), [Phase 5.3](phase5-3/verification-summary.md), [manual sessions](manual-interactive-test-2026-11-12.md), [PDF verification](factual-verification.md), and [final checks/reproducibility](final-review-2026-11-12.md).
