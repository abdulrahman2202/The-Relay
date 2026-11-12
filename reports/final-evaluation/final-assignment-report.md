# Final Assignment Report

Date: 2026-11-12  
Two-page assignment summary using recorded measurements only. Phase 5 manual grading is complete for 13 of 20 questions; 7 operational failures remain ungraded.

## 1. Evidence boundary

| Evidence | Type | Status |
|---|---|---|
| Phase 5 answer quality, 20 questions | Real Groq, prompt `relay-phase3-v1` | Complete |
| Phase 5.3 targeted recheck, A2/A4/A8 | Real Groq, prompt `relay-phase3-v2` | Partial; stopped at A8 |
| Phase 4 calibration, 10 calls | Real Groq | Complete; 9 successful |
| Phase 4 load and retry scenarios | Deterministic mock/stand-in | Simulated |
| Retrieval comparison, 60 measurements | Offline local retrieval | Complete; not simulated |
| Previously recorded local checks | pytest and Ruff | `203 passed, 5 skipped`; Ruff clean; not rerun for this grading update |

Phase 5 and Phase 5.3 are separate runs. Phase 5.3 did not overwrite Phase 5 evidence and did not retest A9-A12.

## 2. Answer-quality results

Phase 5 attempted all 20 questions through the real pipeline with `openai/gpt-oss-20b`, BM25, preset `600`, evidence budget `3000`, `temperature=0`, and `seed=0`.

| Phase 5 result | Count |
|---|---:|
| Questions attempted | 20 |
| Answerable graded `correct` | 5 / 12 |
| Answerable operational failures (ungraded) | 7 / 12 |
| Unanswerable graded `refused_correctly` | 8 / 8 |
| Answered with valid citations | 5 / 5 |
| Final grades assigned | 13 / 20 |
| Questions ungraded | 7 / 20 |

Final Phase 5 grades in `manual-grading.csv`: A1, A3, A5, A6, and A7 are `correct`; U1-U8 are `refused_correctly`. A2, A4, and A8-A12 retain blank final grades for operational failures and are not classified as `wrong` or `refused_wrongly`.

Failures were `citation_validation` for A2, A8, A10, A11, and A12, and `stream_format` for A4 and A9. Mean total latency was `3776.8 ms` for answered, `1211.4 ms` for refused, and `4010.3 ms` for failed turns. A1 included a `10.618 s` retrieval stage, so it is not a typical sample.

Phase 5.3 allowed one attempt per question, used no automatic retries, and stopped at A8 on HTTP `429`.

| ID | Status | Measured outcome |
|---|---|---|
| A2 | answered | 1 claim, 1 valid citation; `42,275.984 ms`; tokens `3,638/290`; retrieval `40,416.505 ms`. Reports Adam, `β1 = 0.9`, `β2 = 0.98`, `4000` warmup steps. Factual grade pending. |
| A4 | failed (`stream_format`) | `1,295.449 ms`; no final answer/claims/citations. Diagnostics retained a claim mentioning `28.4` and `41.8`, but not `41.0`; stream suffix was a single backslash. |
| A8 | failed (`rate_limit`) | HTTP `429`, retryable, `retry_after_seconds=11.0`, `681.792 ms`; no model content, so no parser diagnostics. |
| A9-A12 | not_attempted | Run stopped after A8; no live result. |

Only A2 of the seven targeted Phase 5 failures produced an answer with a valid citation in Phase 5.3; its factual grade remains pending and does not change its ungraded Phase 5 result. A4 still failed, A8 was rejected before any model content was streamed, and A9-A12 are unmeasured.

## 3. Retrieval comparison

The comparison used production retrieval, preset `600`, `top_k=4`, ranking depth `50`, 600/50 boundary chunking, and a 3000-token ceiling.

| Strategy | Complete coverage | MRR | Mean first relevant rank | Unsupported refusals | Mean context tokens | Mean retrieval ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 9 / 12 | 0.6566 | 3.667 | 6 / 8 | 1790.417 | 64.118 |
| BM25 | 11 / 12 | 0.7292 | 1.667 | 6 / 8 | 1839.000 | 125.090 |
| hybrid | 10 / 12 | 0.7778 | 1.833 | 6 / 8 | 1919.083 | 150.977 |

BM25 had the best complete evidence coverage and mean first-relevant rank; hybrid had the best MRR but lower coverage and higher cost. No strategy falsely refused an answerable question. A6 was incomplete for all strategies; A1 was incomplete for vector and hybrid; A9 was incomplete for vector. Coverage measures annotated evidence spans, not answer correctness. U2/U6 were refused at answer level although the evidence gate flagged only 6 of 8 unsupported questions.

## 4. Retry analysis and rate-limit behavior

- **Phase 5, real:** 20 questions used 23 attempts. Three first attempts (U2, U3, U5) received `rate_limit`; each was retried once and completed without another recorded `429`. Other failures were not retried.
- **Phase 5.3, real:** A8 received HTTP `429` with `retry_after_seconds=11.0`; no retry was allowed, so the run stopped and A9-A12 were not measured.
- **Phase 4 calibration, real:** 10 requests produced 9 successes, one deliberate invalid-model error, zero `429` responses, and zero timeouts. TTFT p50/p95/p99 was `757.566/1,511.044/1,578.020 ms` from 3 samples; total latency p50/p95/p99 was `466.627/1,265.984/1,531.804 ms` from 9 samples. Real `429` latency was not measured.
- **Phase 4 retry and load, simulated:** one transient failure recovered with one retry (`1/1`). Against an exhausted per-minute limit, no-retry produced `3/6` successes with 3 rate-limited; retrying produced `3/6` successes but 6 extra attempts. Daily-budget exhaustion was non-retryable (`3/5` successes, 2 rate-limited). Simulated load produced `40/40`, `30/30`, and `25/80` successes for steady, burst, and overload; overload added 35 timeouts and 20 errors. Per-minute limits admitted `30/40` and `15/40`; a daily budget admitted `10/25`. These are not Groq capacity measurements.

## 5. Observability improvements

Phase 5.2 added diagnostics instead of discarding partial output:

- `CitationValidationError` retains the rejected quote and source ID.
- `ClaimStream.failure` retains the error, unparsed suffix, raw/candidate record, last valid record, rejected quote/source, and accepted claims.
- `TurnResult.failure_diagnostics` is persisted per evaluation entry and attempt while the user-visible answer stays empty on failure.
- Quote canonicalization handles formatting-only differences such as NFKC forms, whitespace/table pipes, superscripts, dehyphenation, split fractions, and Unicode math symbols. Matching remains lexical; changed numbers or words still fail.
- Prompt `relay-phase3-v2` requires one JSON object per claim, separate claims for conflicts and multi-part answers, and no prose outside JSON.

A4 in Phase 5.3 demonstrates the benefit: the failed turn retained the last accepted claim, its quoted table row, the source ID, and the trailing backslash. The remaining framing failure is therefore diagnosable without inventing an answer.

## 6. Unmeasured metrics and limitations

- Seven Phase 5 operational failures remain ungraded; Phase 5.3 A2 still requires factual review.
- A4's source inconsistency remains unresolved: Attention Is All You Need reports English-to-German `28.4` BLEU and English-to-French `41.8` in Table 2, but English-to-French `41.0` in the prose on the same physical page 8. Neither value is selected; no final answer exposed both.
- A4 still failed in Phase 5.3; A8 produced no model content; A9-A12 were not attempted.
- Real rate-limit latency distributions and real capacity under load are unmeasured; Phase 4 load/retry results are simulated.
- Failed Phase 5.3 turns lack final token counts; only known input/output counts exist.
- A2's retrieval stage was `40.4 s`, making its total latency an outlier; sample sizes are small.
- U2/U6 required model-level refusal because the evidence gate missed them.
- Retrieval timings are warm local measurements, not Groq end-to-end latency.
- Five integration tests requiring `--run-integration` were skipped.
- Stand-in token counts use a character-based heuristic, not a tokenizer.

## 7. Vaani feedback (user section - intentionally blank)

> **To be completed by the user.** Record Vaani's feedback here. No feedback has been invented or inferred.

## 8. Personal assistant-work reflections (user section - intentionally blank)

> **To be completed by the user.** Record personal reflections on working with the AI assistant here. This report does not attribute any reflection to the user.

## Evidence files

`answer-quality-results.json`, `raw/answer-quality-raw.json`, `evaluation-summary.md`, `submission-readiness.md`, `final-submission-checklist.md`, `retrieval-comparison.csv`, `retrieval-comparison-summary.json`, `raw/retrieval-rankings.json`, `manual-grading.csv`, `failure-analysis.md`, `remediation-report.md`, and `phase5-3/`. Phase 4 evidence remains in `reports/phase4/` and `results/phase4/raw/`.
