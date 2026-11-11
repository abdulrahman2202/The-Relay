# Phase 5 Submission Readiness

Generated: 2026-11-11  
Overall status: **evaluation artifacts ready; not ready for an unqualified "all evaluations passed" claim.** Final answer grading remains pending manual review.

## Readiness checklist

| Check | Status | Evidence |
|---|---|---|
| All 20 Phase 3 questions attempted with the real pipeline | Complete | 20 real end-to-end results |
| Answerable questions answered | Partial | 5 / 12 answered with valid citations; 7 failed before answer |
| Unanswerable questions refused | Complete at answer level | 8 / 8 refused |
| Evidence-gate unsupported detection | Partial | 6 / 8 flagged; U2 and U6 required model-level refusal |
| A4 known source conflict handled | Not demonstrated in an answer | A4 failed with `stream_format`; conflict remains documented for review |
| Retrieval strategies compared | Complete | 60 rows: 20 questions x vector, BM25, hybrid |
| Manual grading worksheet prepared | Complete | 20 rows; final grades intentionally blank |
| Final grades assigned | Pending | User manual review required |
| Full default test suite | Passed | 185 passed, 5 skipped in 113.78 s |
| Full integration suite | Passed per user report | 190 passed |
| Ruff check | Passed | All checks passed |
| Ruff format check | Passed | 37 files already formatted |
| Existing Phase 1-4 evidence preserved | Yes | No prior reports, raw evidence, or CSV rows overwritten |
| API key exposed in artifacts | No | No key written to Phase 5 artifacts |

## Required artifacts present

1. `answer-quality-results.json` - 20 real Groq end-to-end results.
2. `retrieval-comparison.csv` - 60 retrieval measurements.
3. `manual-grading.csv` - 20-row manual review sheet; final grades blank.
4. `evaluation-summary.md` - methodology, results, and limitations.
5. `submission-readiness.md` - this assessment.

Supporting evidence:

- `retrieval-comparison-summary.json`
- `raw/answer-quality-raw.json`
- `raw/retrieval-rankings.json`

## Blocking issues

### 1. Seven answerable questions produced no final answer

`A2`, `A4`, `A8`, `A9`, `A10`, `A11`, and `A12` failed after real attempts:

- `A2`, `A8`, `A10`, `A11`, `A12`: citation validation rejected the supporting quotation.
- `A4`, `A9`: generation did not produce the required structured answer object.

These are observed system outcomes. They were not replaced with synthetic answers. A submission claiming full answer coverage would be inaccurate.

### 2. A4's source conflict was not exposed in an answer

A4 failed before answer generation completed. The known conflict is still documented:

- Table 2 page 8: EN-DE `28.4`, EN-FR `41.8`.
- Prose page 8: EN-FR `41.0`.

The final review must explicitly address the discrepancy. Do not invent a third value or silently choose one without documenting the decision.

### 3. U2 and U6 are not rejected by the evidence gate alone

The final model refused both questions, which is the desired answer-level behavior. However, the literal evidence assessment classified their retrieved context as candidate evidence. The evidence gate therefore missed 2 of 8 unsupported questions; final refusal depended on generation behavior.

### 4. Final grades are blank by design

`manual-grading.csv` has no final grades. The user must review each answer and set the appropriate final grade. The only provisional grades present are `refused_correctly` for the 8 refusals; answered questions were deliberately left ungraded to avoid automatic correctness claims.

## What is ready

- The real 20-question run is complete and reproducible.
- The retrieval comparison is complete with protocol metadata, per-question rankings, coverage, latency, and context-token costs.
- All five answered questions have validated citations.
- All 8 unanswerable questions were refused at the answer level.
- A4's verified conflict and the U2/U6 evidence-gate limitation are documented.
- Existing RM/Relay artifacts and CSV rows were preserved.
- Tests and lint pass.

## Required manual review actions

1. Open `manual-grading.csv` and review each question against its answer, citations, supporting pages, and provisional behavior.
2. Assign final grades using only:
   - `correct`
   - `wrong`
   - `refused_correctly`
   - `refused_wrongly`
3. For A4, explicitly decide how the `41.8` table value versus `41.0` prose value should be represented. Record the decision in `reviewer_notes`.
4. For U2 and U6, note that final refusal occurred despite the evidence gate not rejecting the context.
5. For the 7 failed answerable questions, decide whether to record them as system failures or rerun them under the same production conditions. If rerun, preserve the current raw results first and do not silently overwrite evidence.
6. Do not claim full Phase 5 success until the manual grades and the A4 conflict decision are recorded.

## Recommended next action

Proceed with manual grading and the A4 decision before making any further submission claim. If remediation is requested, address the citation/structured-output failures as a separate approved change, then rerun the affected questions and the full test/lint suite without altering these recorded results.
