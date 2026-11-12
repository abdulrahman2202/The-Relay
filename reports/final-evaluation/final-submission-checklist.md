# Final Submission Checklist

Updated: 2026-11-12. Overall: **NOT READY TO SUBMIT** until the user-input and submission steps below are complete. Item statuses are only COMPLETE, INCOMPLETE, NEEDS USER INPUT, or NOT APPLICABLE. Historical failures are disclosed, not converted to passing grades.

| Item | Status | Evidence / remaining work |
|---|---|---|
| Original assignment brief reviewed against deliverables | NEEDS USER INPUT | No original brief was located. Requirements supplied in this conversation were reviewed; confirm original wording, two-page requirements, naming, and submission destination. |
| Required local retrieval implementation | COMPLETE | `src/retrieval/pipeline.py`, fixed catalog, PDF extraction/chunking, cached MiniLM, Chroma, vector/BM25/hybrid, bounded cited context; RAG tests and historical review. |
| Multi-step orchestration | COMPLETE | `ResearchAssistant.ask()` classifies, plans, retrieves, assesses, streams/validates, checks coverage, and finalizes. |
| Actual tool calls and bounded branching/loops | COMPLETE | `parse_tool_calls()`, tool execution, help/refusal/failure branches, bounded tool/evidence loops and terminal loop; historical real tool-call record under `reports/phase3/implementation-2026-11-11/`. |
| Grounded answers and source/page citations | COMPLETE | Five Phase 5 answers have validated citations and `correct` manual grades; strict quote/numeric checks remain. This is not a universal entailment guarantee. |
| Unsupported-question refusal | COMPLETE | U1–U8 correctly refused in original Phase 5. The evidence gate alone flags 6/8; U2/U6 depend on model refusal. |
| Real Groq integration | COMPLETE | Preserved Phase 3 verification, Phase 4 calibration, Phase 5, and Phase 5.3 evidence. No new external calls. |
| Mock stand-in behavior | COMPLETE | `src/relay/mock/` supports JSON/SSE, deterministic failures, delays, budgets, and telemetry; Phase 4 records/tests. |
| Simulated limits, overload, retries, budget exhaustion | COMPLETE | Phase 4 load/retry summaries and raw JSONL; 273 stand-in rows. Simulations are explicitly labeled. |
| Phase 5.4 multipart completeness | COMPLETE | Bounded quantity/role/value coverage in claim text and its own validated quotations; missing/unrecognized parts fail; tests cover A9 and duplicate-claim cases. |
| Phase 5.4 prompt v3, streaming, diagnostics | COMPLETE | Exact evidence-first examples, escaped formula JSON, clean completion marker, strict suffix rejection, optional redacted CLI diagnostics; relevant relay regression tests. |
| Retry-After minimum-wait correction | COMPLETE | Small final-review fix in `RetryPolicy.delay()`; server minimum now survives cap/jitter. New local regression tests included in final verification. |
| Real and simulated measurement reporting | COMPLETE | Calibration sample sizes and stand-in cohorts kept separate. Buffered ASGI TTFT and failed-metadata limits disclosed in final review. No invented percentiles or real capacity claims. |
| Tokens per answer | COMPLETE | Exact input/output counts for five successful Phase 5 answers are in the report. Missing failed-turn usage is explicitly Not measured. |
| Results CSV schema and validity | COMPLETE | Required `read_results_csv()` check passed: 283 rows (273 stand-in, 10 real); historical file preserved. |
| Retrieval quality/cost comparison | COMPLETE | Preserved 60 rows, coverage/MRR/rank/token/latency table, BM25 choice, refusal limitations, and three actual misleading cases. Unreliable optional `relevant_hits_top_k` counter excluded from conclusions. |
| Original 20-question quality evaluation preserved | COMPLETE | 20 questions, 23 attempts; no historical raw result or original grade overwritten. |
| Manual grading for the 13 gradable Phase 5 outcomes | COMPLETE | A1/A3/A5/A6/A7 correct; U1–U8 refused_correctly; seven operational failures retain blank grades. |
| Successful answers to all 12 original answerable questions | INCOMPLETE | Seven operational failures remain. They are not wrong/refused_wrongly and are not replaced by follow-up results. |
| Phase 5.3 A2 factual review | COMPLETE | Optimizer/betas/warmup verified against Attention v7 p. 7, recorded separately in `factual-verification.md`; original A2 Phase 5 grade remains blank. |
| Phase 5.3 targeted recheck of all seven failures | INCOMPLETE | A2 answered; A4 stream failure; A8 HTTP 429; A9–A12 not attempted. No new model run authorized or needed for this documentation review. |
| Latest manual interactive record and exact metrics | COMPLETE | November 12 sessions preserved separately; all four supplied timing/token rows copied exactly; no unspecified metric invented. |
| Local PDF factual verification | COMPLETE | All eight requested topics checked against exact versions, page/table/equation/paragraph context; limitations and source conflicts explicit. |
| Fully verified later routing/A8 answers | INCOMPLETE | Full generated routing formula/citations and earlier A8 answer/citations are unavailable. Retain provisional/unresolved status unless supplied. |
| A4 and HG38 conflicts documented | COMPLETE | Attention p. 8: 41.8 table versus 41.0 prose. H-Net p. 17: 3.6× less data caption versus 3.6× the amount prose. Neither conflict silently resolved. |
| Final acceptance of unresolved source/answer limitations | NEEDS USER INPUT | Review both source values and the incomplete answer-verification record; do not claim full factual/evaluation success. |
| All ten assignment report sections drafted | COMPLETE | `final-assignment-report.md`; evidence-based assistant-work draft with explicit attribution gaps. |
| Two-page PDF draft | COMPLETE | `final-assignment-report.pdf`: two A4 pages, rendered and visually checked. Personal content remains subject to user review. |
| Vaani feedback | NEEDS USER INPUT | Required placeholder retained; provide actual feedback or explicitly state that none was received. |
| Personal assistant-work reflections/contributions | NEEDS USER INPUT | Confirm the changed/rejected AI approach and personally performed decisions, implementation, testing, and verification. |
| Setup and reproduction instructions | COMPLETE | Updated README/RAG guide and final review; pinned dependencies/cache and historical source revisions recorded; fixed-output scripts restricted to disposable copies. |
| Exact reproduction of every historical live/manual run | INCOMPLETE | External service output/timing cannot be replayed exactly; Phase 5.3 driver and full manual transcripts absent; optional live evaluator overwrite path has a documented defect. |
| Fresh dependency installation / long integration rerun | NOT APPLICABLE | No dependency/retrieval change; no installation/download or long cached-model suite needed for this finalization. |
| Complete default local test suite | COMPLETE | Single run: 276 passed, 5 skipped in 84.00s (0:01:24), exit 0. Five optional integration cases are excluded by default. |
| Ruff check | COMPLETE | Single run: All checks passed!, exit 0. |
| Ruff format verification | COMPLETE | Single run: 70 files already formatted, exit 0. |
| Security and secret review | COMPLETE | No known credential/pattern matches in tracked files, source archives, or reachable history. Local `.env` contains credentials and is ignored; exclude it from uploads. Scan scope/limits recorded in final review. |
| Source-package exclusions and final Git diff | INCOMPLETE | Git diff review and whitespace check passed; only intended changes. Final source archive remains a user action and must exclude `.env`, `.git`, environments, caches, and local indexes. |
| New external API/model calls or quota expansion | NOT APPLICABLE | Prohibited for this task; none made. |
| Final user content review and two-page approval | NEEDS USER INPUT | Check original brief, factual limitations, feedback, attribution, and final PDF after personal edits. |
| Google Drive naming, recipient, and permissions | NEEDS USER INPUT | Exact original submission instructions not available. Confirm before upload. |
| Google Drive upload, access check, and link submission | INCOMPLETE | User action; nothing uploaded or externally shared. |

The exact final command outputs and review limitations are recorded in [final review](final-review-2026-11-12.md). The remaining user actions are in [submission readiness](submission-readiness.md).
