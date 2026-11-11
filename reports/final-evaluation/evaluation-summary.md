# Phase 5 Evaluation Summary

Generated: 2026-11-11  
Status: evaluation evidence complete; final grades pending manual review.

## Scope and method

- Evaluated all 20 Phase 3 questions: 12 answerable (`A1`-`A12`) and 8 unanswerable (`U1`-`U8`).
- Answer quality used the real Relay end-to-end pipeline with Groq `openai/gpt-oss-20b`, prompt `relay-phase3-v1`, strategy `bm25`, preset `600`, evidence budget `3000` tokens, `temperature=0`, and `seed=0`.
- Every question was attempted. Initial rate-limited attempts were retried; the final statuses below are the last real attempts.
- Final answer grades were **not** assigned automatically. `manual-grading.csv` has blank `final_grade` fields for review.
- Retrieval comparison was run offline with production retrieval code on the same 20 questions. It compares `vector`, `bm25`, and `hybrid` (RRF) with the production preset, `top_k=4`, candidate ranking depth 50, and the same 3000-token context ceiling.
- No production defaults, Phase 1-4 reports, raw evidence, or existing `results/results.csv` rows were modified.

## Answer-quality results

Final counts:

| Metric | Count |
|---|---:|
| Questions attempted | 20 |
| Answerable answered | 5 |
| Answerable failed before answer | 7 |
| Unanswerable refused | 8 |
| Answered with valid citations | 5 / 5 answered |
| Final grades assigned | 0 / 20 |

Per-question status:

| ID | Category | Final status | Detail |
|---|---|---|---|
| A1 | answerable | answered | Citations valid; latency outlier at 12.879 s |
| A2 | answerable | failed | `citation_validation`; quotation absent from cited passage |
| A3 | answerable | answered | Citations valid |
| A4 | answerable | failed | `stream_format`; no structured answer produced |
| A5 | answerable | answered | Citations valid |
| A6 | answerable | answered | Citations valid |
| A7 | answerable | answered | Citations valid |
| A8 | answerable | failed | `citation_validation`; quotation absent from cited passage |
| A9 | answerable | failed | `stream_format`; no structured answer produced |
| A10 | answerable | failed | `citation_validation`; quotation absent from cited passage |
| A11 | answerable | failed | `citation_validation`; quotation absent from cited passage |
| A12 | answerable | failed | `citation_validation`; quotation absent from cited passage |
| U1 | unanswerable | refused | Evidence gate flagged insufficient evidence |
| U2 | unanswerable | refused | Model refused; evidence gate did not flag the constraint |
| U3 | unanswerable | refused | Evidence gate flagged insufficient evidence |
| U4 | unanswerable | refused | Evidence gate flagged insufficient evidence |
| U5 | unanswerable | refused | Evidence gate flagged insufficient evidence |
| U6 | unanswerable | refused | Model refused; evidence gate did not flag the constraint |
| U7 | unanswerable | refused | Evidence gate flagged insufficient evidence |
| U8 | unanswerable | refused | Evidence gate flagged insufficient evidence |

Latency summary by final status:

| Status | N | Mean total ms | Min ms | Max ms |
|---|---:|---:|---:|---:|
| answered | 5 | 3776.8 | 834.2 | 12879.5 |
| refused | 8 | 1211.4 | 401.0 | 2678.2 |
| failed | 7 | 4010.3 | 1386.9 | 15940.8 |

The A1 answer included a 10.618 s retrieval stage and should not be treated as a typical latency sample. Failed requests did not produce final answers, so their latency is operationally informative only.

### A4 source conflict

A4 did not produce an answer because generation failed with `stream_format`. Therefore the discrepancy was **not** exposed in a generated answer. The underlying source conflict remains verified and recorded:

- Table 2, physical page 8: Transformer (big) EN-DE `28.4`, EN-FR `41.8`.
- Prose, physical page 8: Transformer (big) EN-FR `41.0`.

The conflict must be explicitly retained during manual review; no third value or silent resolution was invented.

## Retrieval comparison

60 measurements were recorded: 20 questions x 3 strategies. Full details are in `retrieval-comparison.csv`; rankings are in `raw/retrieval-rankings.json`.

| Strategy | Complete coverage | Complete context coverage | False refusals | MRR | Mean first relevant rank | Unsupported refusals | Mean context tokens | Mean retrieval ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| vector | 9 / 12 | 9 / 12 | 0 / 12 | 0.6566 | 3.667 | 6 / 8 | 1790.417 | 64.118 |
| bm25 | 11 / 12 | 11 / 12 | 0 / 12 | 0.7292 | 1.667 | 6 / 8 | 1839.000 | 125.090 |
| hybrid | 10 / 12 | 10 / 12 | 0 / 12 | 0.7778 | 1.833 | 6 / 8 | 1919.083 | 150.977 |

Coverage is based on the resolved gold spans from the audit evidence annotations. It measures whether retrieved chunks cover annotated evidence, not whether a generated answer is correct.

Key observations:

- BM25 had the best complete evidence coverage (`11/12`) and the best mean first-relevant rank (`1.667`).
- Hybrid had the best MRR (`0.7778`) but slightly lower complete coverage (`10/12`) and a higher mean retrieval cost.
- Vector was fastest locally but retrieved complete evidence for only `9/12` answerable questions.
- A6 was incomplete for all three strategies: only one of its two annotated evidence units was covered in the top-4 slice.
- A1 was incomplete for vector and hybrid; A9 was incomplete for vector.
- No strategy falsely refused an answerable question at the evidence-gate stage.
- All strategies found the expected target paper at rank 1 for U2. For U6, BM25 and hybrid found it at rank 1; vector found it at rank 5.
- Retrieval latency is local, warm-condition timing and is not directly comparable to end-to-end Groq latency.

## Interpretation and limitations

- The evaluation is real and not simulated: `measurement_type=real_groq_end_to_end`, `simulated=false`.
- The final answer set is incomplete for answerable questions: 7 of 12 failed before producing an answer. These are valid observed outcomes, not fabricated replacements.
- Citation validation is strict. `citation_validation` failures mean the model's supporting quotation was not found in the cited passage; the answer was rejected rather than reported as valid.
- `stream_format` failures mean the generation output did not match the structured answer protocol; no answer was available for grading.
- U2 and U6 were refused by the model even though the literal evidence gate classified the retrieved passages as candidate evidence. The evidence gate alone is therefore not sufficient to reject all unsupported questions.
- Manual review must assign final grades and decide whether the 7 failed answerable questions are acceptable, rerun-worthy, or evidence of a system limitation.

## Artifacts

- `answer-quality-results.json`: 20 real end-to-end results, citations, assessments, metrics, attempts, and known conflicts.
- `manual-grading.csv`: 20-row human-review worksheet; final grades intentionally blank.
- `retrieval-comparison.csv`: 60-row strategy comparison.
- `retrieval-comparison-summary.json`: protocol and aggregate retrieval metrics.
- `raw/answer-quality-raw.json`: raw answer-quality records.
- `raw/retrieval-rankings.json`: top-50 rankings per question and strategy.
- `evaluation-summary.md`: this report.
- `submission-readiness.md`: readiness assessment and remaining actions.
