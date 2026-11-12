# Final submission review — 2026-11-12

## Scope and evidence boundary

The repository was clean at the start of this review, at commit `10c2088`. No `AGENTS.md` or original assignment brief was found in the repository or searched parent locations. The user was asked for the original brief. This review follows the detailed requirements supplied in the conversation; exact original-brief compliance, submission naming, and Drive recipient/access rules remain unconfirmed.

Reviewed: README, dependency/configuration files, `docs/rag.md`, RAG audit/improvement records, Phase 3/4 completion reports, all Phase 5 summary/analysis/remediation/recheck records, the manual interactive record, relevant implementation and tests, the original PDFs, and Git status/history. No Groq, Gemini, other external API, interactive assistant, evaluation rerun, model download, or dependency installation was performed. The only new execution measurements are the final local verification commands below.

Historical reports describe the state when they were written. In particular, `evaluation-summary.md`, raw answer JSON, and Phase 5.3 records still say grading was pending at capture time. The later manual CSV and [factual review](factual-verification.md) provide the subsequent grading/review decisions without rewriting that history.

## Implementation review

| Component | Inspected implementation | Evidence and limits |
|---|---|---|
| Fixed corpus, indexing, retrieval | `src/retrieval/catalog.py`, `pipeline.py`, `context.py`; RAG guide and improvement review | Three exact PDF hashes/versions; local cached MiniLM; Chroma; vector/BM25/RRF; bounded context and physical-page provenance. Relevant tests include `tests/rag/test_catalog.py`, `test_pipeline.py`, `test_context.py`, `test_regressions.py`, and optional `test_integration.py`. |
| Multi-step orchestration and tool calls | `ResearchAssistant.ask()` / `_prepare()` in `src/relay/orchestrator.py`; `parse_tool_calls()` / `ResearchTool.execute()` in `tools.py` | Real structured tool planning, bounded tool loop, evidence-selection loop, help/refusal/failure branches, independent interactive turns. Historical real evidence: `reports/phase3/implementation-2026-11-11/real-groq-verification.json`. |
| Phase 5.4 multipart coverage | `infer_answer_parts()` / `assess_answer_coverage()` in `src/retrieval/evidence.py`; `ClaimStream.finish()` | Recognized quantities/roles/values are required in claim text and that claim's validated quotations; supported table comparisons bind row/column. No claim-count test or gold-answer lookup. Unknown coordinated parts fail with `incomplete_answer`. Single questions outside the grammar retain the citation contract (`not_required`), so this is not a universal completeness/entailment guarantee. |
| Citations and streaming | `validate_claim()`, `_canonical_positions()`, `_object_end()`, `ClaimStream` in `src/relay/citations.py` | Formatting-only canonicalization, source-derived offsets/pages, numeric support, escaped strings, adjacent objects, exactly one clean completion marker, and rejection of malformed trailing content. Failed turns clear final answer/claims; earlier streamed text can remain visible with an incomplete-response notice. |
| Prompt v3 | `src/relay/prompts.py`, `PROMPT_VERSION = relay-phase3-v3` | Exact evidence before claim composition, no paraphrasing in quote fields, numerical notation preserved, synthetic examples for tables/conflicts/captions/formula plus explanation. No evaluation answers embedded as prompt evidence. |
| Failure diagnostics | `display_failure_diagnostics()` / `_diagnostic_value()` in `src/relay/cli.py` | Optional `--diagnostics`; rejected/candidate quotations, source IDs, last valid claim, malformed suffix, unsupported numbers, and missing parts when available. Text is bounded, escaped, and redacted. `--json` is a separate mode; do not assume its raw diagnostic fields receive the terminal display's redaction. |
| Real Groq adapter | `src/relay/llm.py`, `config.py`, `budget.py` | Separate planning/generation timing and known usage, bounded request/turn deadlines, sanitized errors, SDK automatic retries disabled. Local tests use fake transports; real behavior is supported only by preserved historical requests. |
| Stand-in, queue, retries, load harness | `src/relay/mock/`, `reliability.py`, `loadtest.py` | Deterministic JSON/SSE service, minute/daily budgets, overload, bounded in-process admission, retry policy, ASGI load harness, and CSV reader/writer. Tests: `tests/relay/test_mock_service.py`, `test_reliability.py`, `test_loadtest.py`. |

Phase 5.4 regression coverage was inspected in `tests/rag/test_answer_coverage.py` and `tests/relay/test_citations.py`, `test_orchestrator.py`, `test_prompts.py`, and `test_terminal.py`. Cases include missing A9 initialization despite a quote containing it, duplicate claims, a single claim covering multiple parts, unknown conjuncts, A4 unsupported numbers after a valid claim, A10 table/number attribution, A11 exact caption quotation, A12 escaped formulas/invalid suffixes, and secret-safe terminal diagnostics. These deterministic tests are not new live factual-quality measurements.

### Necessary reliability correction

One rate-limit policy defect justified a small code change under the user's critical-defect exception. Previously `RetryPolicy.delay()` capped the chosen server delay and then applied jitter, so a `Retry-After` of 4 seconds could become 2 seconds, and negative jitter could shorten smaller server waits. The corrected method preserves the server delay as a minimum after cap/jitter, while retaining the existing give-up rule above `max_retry_after_seconds`.

Only `src/relay/reliability.py` and its existing test module changed. New regression cases cover the cap, negative jitter, the manager waiting before its next attempt, and preservation of the explicitly simulated `respect_retry_after=False` experiment. The live CLI's retry behavior, RAG pipeline, citations, prompts, and Phase 5.4 coverage are unchanged. No stand-in or real benchmark was rerun; the old results describe the old implementation.

## Measurements and historical separation

| Evidence | Actual scope | Interpretation |
|---|---|---|
| `results/results.csv` and `reports/phase4/` | 283 historical rows: 273 stand-in and 10 real calibration | Only the calibration rows are real Groq. All `answer_grade` fields are blank; quality was not measured in Phase 4. |
| `answer-quality-results.json` and `raw/answer-quality-raw.json` | Original Phase 5: 20 questions, 23 question attempts; prompt v1 | Five correct answers, eight correct refusals, seven operational failures. `manual-grading.csv` has 13 assigned grades and seven blanks. No failed request is graded wrong/refused wrongly. |
| `failure-analysis.md` / `remediation-report.md` | Phase 5.1 diagnosis / Phase 5.2 changes | Gold evidence was retrieved for all seven failed questions; exact original rejected quotes/suffixes were not retained. Later diagnostics make such failures inspectable, but cannot recover the old missing strings. |
| `phase5-3/` | Targeted prompt-v2 recheck | A2 answered with valid citation; its factual review is now correct in `factual-verification.md`. A4 stream failure; A8 HTTP 429; A9–A12 unattempted. Original metadata and Phase 5 grades remain unchanged. |
| Phase 5.4 source and tests | Local reliability improvements, prompt v3 | No new controlled answer-quality evaluation. |
| `manual-interactive-test-2026-11-12.md` | User-reported interactive observations | Older failures and latest BLEU/routing/definition/refusal outcomes retained separately, with exact supplied timings/tokens. Model identifier, prompt version, full transcript, and some quotations/formulas were not supplied. |

The report copies the recorded Phase 4 percentiles and their sample counts; it does not recompute percentiles across phases or real/simulated cohorts. Calibration's nine successful totals combine three non-streaming, three streaming, and three concurrent non-streaming requests; the three TTFT samples are streaming only. They are small shared-service observations, not a real capacity benchmark.

**Transport/timing limitation:** `run_load_scenario()` uses HTTPX 0.28.1 `ASGITransport`. Its installed transport accumulates response body parts and returns the response after the app completes. Consequently the stand-in's recorded `first_token_ms` is client-observed buffered delivery, not time of the first emitted SSE token over a socket. It also starts within the successful attempt, whereas total latency includes manager waiting/retries. Preserve the recorded values; real network TTFT for the stand-in is **Not measured**. Successful burst queue timings still demonstrate waiting under this harness.

Failed stand-in results do not retain all server-response metadata in `ManagedResult.value`; the load writer substitutes zero for missing server queue wait. Failed server-queue timing and usage across all retry attempts therefore cannot be reconstructed completely. Do not treat every zero as proof of no server wait, or final-attempt usage as total retry cost. Real 429 percentiles, sustained real throughput, provider-only compute time, and a held-out factual-quality evaluation are **Not measured**.

## Retrieval comparison and concrete misleading cases

The preserved 60-row comparison uses preset 600, overlap 50, boundary chunking, top-4 evidence, ranking depth 50, and a 3000-token ceiling. BM25 uses k1=1.5/b=0.75; hybrid uses equal-weight RRF with constant 60. Each strategy receives a warmup before timing. Coverage, MRR, first relevant rank, and mean context size use 12 answerable questions; mean retrieval latency uses all 20 questions per strategy.

| Strategy | Complete retrieved/context coverage | MRR | Mean first relevant rank | Mean context tokens | Mean retrieval ms | Evidence-gate refusals |
|---|---:|---:|---:|---:|---:|---:|
| Vector | 9/12 | 0.6566 | 3.667 | 1790.417 | 64.118 | 6/8 |
| BM25 | 11/12 | 0.7292 | 1.667 | 1839.000 | 125.090 | 6/8 |
| Hybrid | 10/12 | 0.7778 | 1.833 | 1919.083 | 150.977 | 6/8 |

BM25 remains the operational choice for coverage and mean first relevant rank. Hybrid leads MRR but costs more time/context and misses one additional complete evidence set; vector is fastest. These results do not establish a universally best retriever. U2/U6 require model-level refusal despite candidate evidence; no answerable evidence-gate refusal was observed. The earlier RAG audit's 17-question/4096-token experiment is a different protocol and is not pooled with this comparison.

Three examples grounded in `raw/retrieval-rankings.json` and the saved annotations:

1. **Wrong model's measurement (U8):** vector rank 1 is Attention p. 8, chunk `083f8af225205118e3b7fd44bcde9911b7e27cf3594f7993c3ad70da1b6155e3`. It contains Transformer BLEU `28.4`, although the question asks for H-Net WMT results. The evidence gate reports missing BLEU/WMT in H-Net; copying the number would be misattribution.
2. **Incomplete multipart evidence (A6):** top-4 coverage is one of two annotated units for every strategy. Saved vector hits have `[false, true]`: training-token support without the required parameter evidence. The gate still labels it candidate evidence. This comparison uses the original question; Phase 5's model-generated tool query is a separate retrieval path and produced an answer supported by Moshi p. 3.
3. **Wrong quantity (U6):** BM25 rank 1 is the same Attention p. 8 chunk, supplying training time, hardware, and FLOPs for a carbon-footprint question. The gate passes because those literal topic checks do not establish carbon emissions. The real Phase 5 model refused; neither a dollar cost nor emissions should be inferred from the compute figures.

**Unused counter defect:** `scripts/evaluate_retrieval_configs.py` calculates `relevant_hits_top_k` using the truthiness of a nonempty list of coverage flags. That historical column is not a trustworthy count of relevant hits. The requested coverage, MRR, and first-rank calculations use `all`/`any` separately and are not affected. No historical CSV was edited; this unused field is excluded from the final report's conclusions. Correcting that optional evaluator counter is outside the critical application fix.

## Security and deliverable hygiene

A local scan inspected 200 tracked files, 221 reachable historical Git blobs across 11 commits, and the contents of three tracked source ZIP archives (25, 37, and 32 members). It searched for known local credential values, common provider/GitHub/AWS key patterns, private-key material, and credential-bearing URLs. It found no matches in tracked deliverables, scanned archives, or reachable history. Secret values were never printed.

The local `.env` **contains credentials**, is untracked, and is ignored. `.env.example` contains placeholders. There is no evidence here of committed credential exposure; exclude `.env` and private environment configuration from every upload. Pattern/value scanning cannot guarantee detection of every possible unknown or encoded secret. The final diff must also be reviewed before packaging, especially any later user-added transcript or reflection.

Exclude `.git/`, `.venv/`, `.env`, caches (`.cache/`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`), and local `data/chroma*/` databases from a source submission unless the original brief explicitly requires a data artifact. They are generated/local state, not required source. Keep the supplied PDFs, maintained source/tests/scripts, dependency files, README/docs, results CSV, and historical reports/raw evidence/source archives. No user file, database, report, or Git history was deleted.

The old manual Groq scripts in `tests/test_model.py` and `tests/groqtest.py` use environment credentials rather than embedded keys, but execute remote requests on import/execution. Default pytest explicitly excludes them. Do not run `pytest tests` as an offline substitute for the configured command.

## Reproducibility and remaining limits

Setup and normal commands are in [README](../../README.md) and [the RAG guide](../../docs/rag.md). Python 3.12.2 was the recorded development environment; `pyproject.toml` pins runtime/dev dependencies and `requirements.txt` constrains transitive packages. These were reviewed locally, not reinstalled in a clean environment. MiniLM revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf` must already be cached or provisioned separately. Fresh ingestion checks the supplied PDF hashes and creates fingerprinted collections; changing dependencies may require a new index. HNSW results, CPU timings, and real service behavior are not guaranteed bit-for-bit reproducible.

For **offline reproduction only**, first extract/copy the project into a disposable directory and create its own environment. The fixed-output scripts below overwrite results relative to their script directory, so never run them over the submission copy:

```powershell
# In the disposable copy, after setup and with the pinned local model cached:
.venv\Scripts\python.exe -m retrieval ingest --preset 600
.venv\Scripts\python.exe scripts/evaluate_retrieval_configs.py
.venv\Scripts\python.exe scripts/run_phase4_experiments.py
# To omit the stored real calibration rows when running the stand-in:
.venv\Scripts\python.exe scripts/run_phase4_experiments.py --skip-real
# The broader historical RAG protocol has a configurable fresh output directory:
.venv\Scripts\python.exe scripts/evaluate_rag.py --output reports/rag/evaluation-new-run
```

The stand-in driver merges stored calibration rows by default; that merge does not make a real call. Do not run both stand-in commands merely to validate the submission; they describe alternative reproduction modes. Exact historical source snapshots are available in the RAG source ZIPs; Git revisions identify Phase 4 (`475b3c0`), original Phase 5/prompt v1 (`222ef16`), Phase 5.2/prompt v2 (`d92db82`), and Phase 5.4/prompt v3 (`10c2088`). Use the appropriate source in an isolated copy for a historical protocol, rather than attributing the old measurements to the final retry fix.

`scripts/calibrate_phase4.py`, `scripts/verify_phase3.py`, and `scripts/evaluate_final_answers.py` make real Groq calls and were not run. Their saved configurations/questions support inspection of the old protocol, not exact replay of the provider. The live evaluator writes fixed result/grade paths and must not run over the historical package. Its optional `--overwrite` initializer currently attempts to unpack an empty dictionary; that path is not a supported reproduction route in this review. The Phase 5.3 one-attempt/stop-on-429 driver and the full manual transcripts are not present as standalone reproducible scripts. These are documented reproduction limits, not reasons to spend more API quota now.

The two-page PDF is a draft of `final-assignment-report.md`. It was generated locally with PyMuPDF and the already installed Markdown parser: two A4 pages, 10-point body text, 8-point tables, no automatic scaling. Both rendered pages were visually checked for readable text, complete sections, table fit, and clipping. Final content approval, feedback/reflection completion, and original-brief comparison remain user actions. After any personal edits, regenerate/export the report and confirm it is still two pages. No Drive upload or permission change was made.

## Final local verification

The following commands were each executed **once**, after all scoped code/documentation changes. The explicit interpreter is the project equivalent of the requested `python`. Only verification-status bookkeeping was added afterward; the tested implementation did not change.

```text
.venv\Scripts\python.exe -m pytest -q
.................................................................ss..... [ 25%]
.....................sss................................................ [ 51%]
........................................................................ [ 76%]
.................................................................        [100%]
=========================== short test summary info ===========================
SKIPPED [1] tests\rag\test_embeddings.py:82: Pass --run-integration to use the pinned local model
SKIPPED [1] tests\rag\test_embeddings.py:89: Pass --run-integration to use the pinned local model
SKIPPED [3] tests\rag\test_integration.py:7: Pass --run-integration to use the pinned local model
276 passed, 5 skipped in 84.00s (0:01:24)

.venv\Scripts\python.exe -m ruff check src tests scripts
All checks passed!

.venv\Scripts\python.exe -m ruff format --check src tests scripts
70 files already formatted

.venv\Scripts\python.exe -c "from pathlib import Path; from relay.loadtest import read_results_csv; print('Validated rows:', len(read_results_csv(Path('results/results.csv'))))"
Validated rows: 283
```

All four commands exited with code **0**. The complete default suite finished with **276 passed, 5 skipped in 84.00s (0:01:24)**. The five skips are two cached-MiniLM embedding cases and three corpus/preset integration cases; `--run-integration` was not enabled. No long integration suite or live evaluation was rerun. Ruff reported **All checks passed!**; format verification reported **70 files already formatted**. The required CSV validator reported **Validated rows: 283**.

A separate read-only CSV inspection confirmed 273 stand-in rows (160 ok, 58 rate-limited, 35 timeout, 20 error) and 10 real rows (9 ok, 1 error), all 283 answer grades blank, unique request IDs, parseable timestamps, and no negative recorded timing/token/retry values. New/changed documents and the rendered report had no known credential/pattern matches; all checked local documentation links resolved.

`git diff --check` exited **0**; its only messages were Windows LF-to-CRLF notices. A protected-path `git diff --exit-code` exited **0** for original results/grades, supplied papers, all earlier phase/audit records, retrieval source, and Phase 5.4 citations/orchestrator/prompts/CLI. The change list contains the README, RAG guide, six final-evaluation Markdown documents, the two-page PDF, and the retry policy/test file; no file was deleted. See the exact list below.

Files changed (eight modified, three new):

- `README.md`
- `docs/rag.md`
- `src/relay/reliability.py`
- `tests/relay/test_reliability.py`
- `reports/final-evaluation/manual-interactive-test-2026-11-12.md`
- `reports/final-evaluation/final-assignment-report.md`
- `reports/final-evaluation/final-submission-checklist.md`
- `reports/final-evaluation/submission-readiness.md`
- `reports/final-evaluation/factual-verification.md` (new)
- `reports/final-evaluation/final-review-2026-11-12.md` (new)
- `reports/final-evaluation/final-assignment-report.pdf` (new)
