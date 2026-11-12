# Phase 5 Submission Readiness

Generated: 2026-11-11  
Updated: 2026-11-12 with Phase 5 manual grading and separate Phase 5.3 outcomes  
Overall status: **evaluation artifacts ready; Phase 5.3 remains incomplete; not ready for an unqualified "all evaluations passed" claim.** Phase 5 manual grading is complete for 13 of 20 questions; 7 operational failures remain ungraded.

## Readiness checklist

| Check | Status | Evidence |
|---|---|---|
| All 20 Phase 3 questions attempted with the real pipeline | Complete | 20 real end-to-end results |
| Answerable questions answered | Partial | 5 / 12 graded `correct` with valid citations; 7 operational failures ungraded |
| Unanswerable questions refused | Complete | 8 / 8 graded `refused_correctly` |
| Evidence-gate unsupported detection | Partial | 6 / 8 flagged; U2 and U6 required model-level refusal |
| A4 known source conflict handled | Pending | A4 failed with `stream_format`; source conflict remains unresolved and documented for review |
| Retrieval strategies compared | Complete | 60 rows: 20 questions x vector, BM25, hybrid |
| Manual grading worksheet prepared | Complete | 20 rows; 13 final grades assigned; 7 operational failures retain blank grades |
| Phase 5 manual grading | Complete for 13 / 20 questions | 5 `correct`; 8 `refused_correctly`; 7 / 20 ungraded |
| A2 Phase 5.3 factual review | Pending | Answered with a valid citation; factual grade still pending |
| Phase 5.3 targeted live verification | Partial | A2 answered; A4 failed; A8 rate-limited; A9-A12 not attempted |
| Full default test suite | Passed | 203 passed, 5 skipped in 96.24 s (2026-11-12) |
| Full integration suite | Passed per user report | 190 passed |
| Ruff check | Passed | All checks passed |
| Ruff format check | Passed | 68 files already formatted |
| Existing Phase 1-4 evidence preserved | Yes | No prior reports, raw evidence, or CSV rows overwritten |
| Original Phase 5 evidence preserved | Yes | Phase 5.3 artifacts written separately under `phase5-3/` |
| API key exposed in artifacts | No | No key written to Phase 5 or Phase 5.3 artifacts |

Test and lint statuses above are prior recorded results; no tests, lint, or API calls were run for this grading update.

## Required artifacts present

1. `answer-quality-results.json` - 20 real Groq end-to-end results.
2. `retrieval-comparison.csv` - 60 retrieval measurements.
3. `manual-grading.csv` - 20-row manual review sheet; 13 final grades assigned; 7 operational failures ungraded.
4. `evaluation-summary.md` - methodology, results, and limitations.
5. `submission-readiness.md` - this assessment.
6. `final-assignment-report.md` - two-page assignment summary using measured results only.
7. `final-submission-checklist.md` - claim controls, artifact status, and user-review gates.

Supporting evidence:

- `retrieval-comparison-summary.json`
- `raw/answer-quality-raw.json`
- `raw/retrieval-rankings.json`

## Phase 5.3 live verification outcomes

Phase 5.3 used the real Relay pipeline and the real Groq API with `openai/gpt-oss-20b`, prompt `relay-phase3-v2`, BM25, preset `600`, evidence budget `3000`, `temperature=0`, and `seed=0`. It allowed one attempt per question and no automatic retries. The run stopped at A8 after Groq returned HTTP `429` with `retry_after_seconds=11.0`.

| ID | Status | Measured outcome |
|---|---|---|
| A2 | answered | 1 claim, 1 valid citation, `42275.984 ms`, tokens `3638/290`; factual grade pending |
| A4 | failed (`stream_format`) | `1295.449 ms`; no final answer/claims/citations; diagnostics retained an accepted claim mentioning `41.8` but not `41.0`; stream suffix was `\` |
| A8 | failed (`rate_limit`) | HTTP `429`, retryable, `retry_after_seconds=11.0`, `681.792 ms`; no model content, so no parser diagnostics |
| A9-A12 | not_attempted | Run stopped after A8; no live result |

This verification does **not** show that all seven Phase 5 failures are fixed. Only A2 produced an answer with a valid citation in Phase 5.3; its factual grade remains pending and does not change its ungraded Phase 5 result. A4 remained a `stream_format` failure, A8 was rejected before generation, and A9-A12 were not measured.

Phase 5.3 artifacts:

- `phase5-3/live-results.json`
- `phase5-3/live-results.csv`
- `phase5-3/verification-summary.md`

## Blocking issues

### 1. Seven answerable questions produced no final answer

In Phase 5, `A2`, `A4`, `A8`, `A9`, `A10`, `A11`, and `A12` failed after real attempts:

- `A2`, `A8`, `A10`, `A11`, `A12`: citation validation rejected the supporting quotation.
- `A4`, `A9`: generation did not produce the required structured answer object.

These are observed system outcomes. They were not replaced with synthetic answers. A submission claiming full answer coverage would be inaccurate.

Phase 5.3 partially rechecked the targeted set: A2 answered with a valid citation, A4 again failed with `stream_format`, A8 hit a real HTTP `429` before generation, and A9-A12 were not attempted. It is not a full seven-question pass.

### 2. A4's source conflict was not exposed in an answer

A4 failed before answer generation completed. Attention Is All You Need contains an unresolved source inconsistency:

- Table 2, physical page 8: English-to-German `28.4` BLEU; English-to-French `41.8` BLEU.
- Prose on the same physical page 8: English-to-French `41.0` BLEU.

Neither conflicting value is selected. Final review must explicitly document the discrepancy and how both values will be represented.

### 3. U2 and U6 are not rejected by the evidence gate alone

The final model refused both questions, which is the desired answer-level behavior. However, the literal evidence assessment classified their retrieved context as candidate evidence. The evidence gate therefore missed 2 of 8 unsupported questions; final refusal depended on generation behavior.

### 4. Seven operational failures remain ungraded

`manual-grading.csv` records 5 `correct` answers (A1, A3, A5, A6, A7) and 8 `refused_correctly` refusals (U1-U8): 13 of 20 questions graded. The 7 Phase 5 operational failures (A2, A4, A8-A12) retain blank final grades and are not classified as `wrong` or `refused_wrongly`. Manual grading is complete for the 13 graded questions; Phase 5.3 A2 factual review remains pending separately.

## What is ready

- The real 20-question run is complete and reproducible.
- The retrieval comparison is complete with protocol metadata, per-question rankings, coverage, latency, and context-token costs.
- All five answered questions are graded `correct` and have validated citations.
- All 8 unanswerable questions are graded `refused_correctly`.
- A4's verified conflict and the U2/U6 evidence-gate limitation are documented.
- Phase 5.3 real outcomes and diagnostics are preserved separately from the original Phase 5 run.
- Existing RM/Relay artifacts and CSV rows were preserved.
- Prior recorded tests and lint: `203 passed, 5 skipped`; Ruff check and format clean on 2026-11-12.

## Required manual review actions

1. Complete the A2 Phase 5.3 factual review and record its grade separately from Phase 5.
2. Review the unresolved A4 source conflict and document how both `41.8` (Table 2) and `41.0` (prose) will be represented.
3. Add Vaani feedback in the marked final-report section.
4. Add personal assistant-work reflections in the marked final-report section.
5. Complete final user review and submission.

## Recommended next action

Complete the pending A2 Phase 5.3 factual review, A4 source-conflict review, Vaani feedback, and personal assistant-work reflections before final user review and submission.
