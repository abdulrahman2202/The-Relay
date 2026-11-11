**The approved RAG implementation, review and cleanup are complete. Retrieval results are mixed.**
The original Moshi latency miss is resolved at 300 tokens/top-3, and extraction now
retains more useful numeric and layout information. Other questions regress at
small retrieval cutoffs. Vector remains the default; BM25 and hybrid retrieval are
explicit options. These measurements do not justify a universally preferred strategy.
This phase ends at cited retrieval, context preparation and evidence checks.

This review uses the [original audit](../audit-2026-11-11/report.md), its reviewed
evidence annotations, and the final `relay-rag-v2.1` run in
[evaluation-final](evaluation-final/summary.json). The earlier implementation run
in [evaluation](evaluation/summary.json) is preserved separately. All values below
refer to the final run unless explicitly labeled otherwise.

**Implementation and review decisions.**

| Area | Implemented behavior | Trade-off or boundary |
| --- | --- | --- |
| PDF extraction | Original PDF spans supply cell text; detected geometry supplies table regions and row separators. Superscripts retain explicit notation, including signed exponents. Alphabetic line-end hyphenation is joined within text blocks. | Table detection can be ambiguous. General equations, fractions and image-only content still need the PDF. Joining can remove a genuine compound-word hyphen. |
| Sections and figures | Bookmark titles are matched on their bookmarked page. Table regions cannot become headings; strict typography/text rules provide a fallback. Rotated figure labels are retained while the arXiv margin stamp is filtered. | This is heuristic layout processing, not a complete document-layout parser. |
| Chunking | Configurable `boundary` mode prefers sections, sentences and table rows; a fitting table stays together. Orphaned parent headings accompany their child section. Text is recounted after slicing, and boundaries avoid cuts inside words/numbers. `fixed` mode remains available. | More, shorter chunks change ranking and storage costs. Oversized sentences and tables can still lose surrounding context. |
| Retrieval | Vector, local BM25, and optional equal-weight Reciprocal Rank Fusion operate over the same Chroma records. Scores identify their method; lexical-only distances are null. | BM25 favors literal terms; fusion can demote useful results. The lexical index is rebuilt per request for this small corpus. |
| Context | Query-focused sentence/row selection, duplicate/contained-passage suppression and budget redistribution make room for later hits. Whole passages are restored when capacity permits. | Lexical focusing can still omit a necessary fact; it is not an evidence-entailment model. Partial overlap is not universally removed. |
| Attribution | Every selected fragment retains adjusted source spans, physical pages, paper/version, a versioned URL, parent chunk ID and paper-relative character position. | Physical PDF pages can differ from printed labels; a multi-page URL opens its first cited page. |
| Refusal support | `retrieve()` checks explicit evidence requirements and limited automatically recognized model, metric, hardware, date and parameter-count constraints against the bounded context. | `candidate_evidence` means literal constraints passed, not that the complete answer is supported. Absence from retrieved context does not prove absence from the corpus. |
| Reproducibility | Pipeline revision and chunking settings identify new collections in `data/chroma-v2/`. Model revision, local CPU embedding/window pooling and deterministic IDs remain pinned. | Embedding inference remains local. HNSW membership and floating-point results need not be identical across machines or dependency changes. |

Review fixes included retaining original spans instead of table-parser cell strings
that can reorder decimal points, joining adjacent superscript fragments, preventing
standalone parent-heading chunks, revalidating PDF hashes when using cached
extraction, and redistributing context space unused by short passages. New
regressions cover the latter three cases. The initial implementation suite passed
90 tests; after these fixes the complete configured suite passed 93 tests.

The final review checked all changed source, tests and documentation against the
archived baseline. It checked exact token recounting, citation-header/separator
costs, clipped source offsets, nullable lexical distances, strategy-independent
collection identity, index readiness, retry behavior and input validation. The
public `search()` and `retrieval.pipeline.build_context` interfaces remain
available. `retrieve()` adds bounded context and evidence assessment without an
LLM call. No new runtime dependency was added.

**Observed extraction and provenance results.**

| Paper | Version | Physical pages | Original chunks, 300 / 600 / 900 | Final chunks, 300 / 600 / 900 |
| --- | --- | ---: | --- | --- |
| Attention Is All You Need | 1706.03762v7 | 15 | 38 / 17 / 11 | 52 / 36 / 28 |
| Moshi: a speech-text foundation model for real-time dialogue | 2410.00037v1 | 66 | 192 / 88 / 57 | 216 / 105 / 79 |
| Dynamic Chunking for End-to-End Hierarchical Sequence Modeling | 2507.07955v2 | 39 | 150 / 68 / 44 | 175 / 102 / 66 |
| Total | Exactly three papers | 120 | 380 / 173 / 112 | 443 / 243 / 173 |

The final [protocol](evaluation-final/protocol.json) validates 859 indexed records
and 1,240 source spans against extracted pages, including text, token counts,
titles, versions, PDF hashes and page lists. There are zero observed chunk starts
or ends inside words/numbers in boundary mode. The original audit counted starts /
ends of 53 / 46, 34 / 31 and 10 / 12 for the three sizes. These are boundary checks,
not a measurement of semantic chunk quality.

Regression checks on the actual PDFs confirm:

- Moshi p. 1 retains `theoretical latency of 160ms, 200ms in practice`; p. 11
  retains `Q = 8`, `NA = 2048`, `12.5Hz` and `1.1kbps`.
- Attention p. 8 retains `Transformer (big) | 28.4 | 41.8` and
  `2.3 · 10^{19}`. Moshi p. 8 retains the signed exponent `10^{−4}`.
- H-Net p. 17 keeps the Transformer and H-Net rows with `0.599` and `0.663`;
  the table has an explicit region and row separators.
- The audited false section labels beginning `38.1`, `1920`, `56.4` and
  `A natural question` are absent. Moshi's actual section 5.3 and 5.5 headings
  remain correctly recognized on pp. 25 and 29.
- Moshi p. 60 retains the rotated `block=32` and `block=256` labels; H-Net p. 13
  retains `Validation Bits-per-byte`.

All 120 pages were extracted without an empty-page, duplicate-page or fatal
extraction issue in this corpus. The new extractor reports 15 table-layout and
five math-layout warnings. Reporting uncertainty is intentional; these checks do
not establish full table, equation or figure accuracy. See
[extraction.json](evaluation-final/extraction.json) and the ingestion reports for
the exact page-level text and issues.

**The Moshi latency case now returns the requested values.**

For the unchanged question, “What are the theoretical and practical latency of
Moshi full-duplex speech dialogue?”, the original 300-token vector answer chunk
ranked 24th. The final answer chunk ranks second with vector retrieval, first with
BM25 and first with hybrid. All three final top-3 results contain complete
annotated evidence for this question.

The actual rank-2 vector passage includes:

> Our resulting model is the first real-time full-duplex spoken large language model, with a theoretical latency of 160ms, 200ms in practice, and is available at github.com/kyutai-labs/moshi.

It cites [Moshi v1, physical p. 1](https://arxiv.org/pdf/2410.00037v1#page=1), chunk
`53b84cdd1b48157d8e21ebfe78538818ff0c66b5af45c1283fc86c9e8cd63a37`.
The saved [CLI retrieval](moshi-vector.json) also retains both values in its
718-token cited context. The original miss was a ranking problem, not loss of
these particular numbers during extraction. The combined extraction/chunking
change improved this case; this run does not isolate the contribution of each change.

**Retrieval evaluation used the same questions and evidence rules.**

The [evaluation script](../../../scripts/evaluate_rag.py) uses the production
retrieval, context and evidence functions with the audit's 12 answerable questions
(four per paper) and five unsupported questions. It checks top-3, top-5 and top-10,
plus the native top-4 for 600-token chunks. Overlap is 50; the model is the pinned
local MiniLM revision; BM25 uses k1=1.5 and b=0.75; RRF uses 50 candidates per
retriever and constant 60. Primary searches have no paper filter. Context is
capped at 4,096 MiniLM tokens, including citations and separators. Python socket
connections were blocked; no answer generation was performed.

Annotations are aligned before retrieval. One recorded
[presentation adaptation](evaluation-final/evidence-adaptations.json) changes
H-Net Table 4's header order from `Model, Chinese, Code` to geometric
`Chinese, Code, Model`; labels, required values and factual rules are unchanged.
The metric is **complete annotated evidence coverage** across the union of
returned passages from the correct paper. It is not answer accuracy, precision,
entailment, latency or a held-out benchmark. Both extraction and chunking changed,
so before/after differences are effects of the combined implementation.

Each cell is **original audit → final**, out of the same 12 answerable questions:

| Strategy | Chunk tokens | Complete evidence @3 | @5 | @10 |
| --- | ---: | --- | --- | --- |
| Vector | 300 | 10 → 9 | 11 → 10 | 11 → 10 |
| Vector | 600 | 11 → 9 | 12 → 10 | 12 → 12 |
| Vector | 900 | 10 → 9 | 11 → 11 | 12 → 12 |
| BM25 | 300 | 11 → 9 | 11 → 12 | 12 → 12 |
| BM25 | 600 | 12 → 11 | 12 → 12 | 12 → 12 |
| BM25 | 900 | 11 → 11 | 12 → 12 | 12 → 12 |
| Hybrid RRF | 300 | 10 → 10 | 10 → 11 | 12 → 11 |
| Hybrid RRF | 600 | 12 → 10 | 12 → 12 | 12 → 12 |
| Hybrid RRF | 900 | 11 → 12 | 12 → 12 | 12 → 12 |

**Native settings and delivered context must be assessed together.**
The two coverage columns below also use original → final counts out of 12.
Context token means cover those 12 questions and are rounded to one decimal.

| Strategy | Native preset | Retrieved coverage | Context coverage | Mean cited-context tokens |
| --- | --- | --- | --- | --- |
| Vector | 300 / top-3 | 10 → 9 | 10 → 9 | 981.5 → 826.2 |
| Vector | 600 / top-4 | 11 → 10 | 11 → 10 | 2532.3 → 1819.9 |
| Vector | 900 / top-5 | 11 → 11 | 11 → 11 | 3737.8 → 2685.2 |
| BM25 | 300 / top-3 | 11 → 9 | 11 → 9 | 982.2 → 798.5 |
| BM25 | 600 / top-4 | 12 → 12 | 12 → 12 | 2534.1 → 1862.8 |
| BM25 | 900 / top-5 | 12 → 12 | 12 → 12 | 3738.4 → 3156.5 |
| Hybrid RRF | 300 / top-3 | 10 → 10 | 10 → 10 | 982.0 → 826.1 |
| Hybrid RRF | 600 / top-4 | 12 → 11 | 12 → 11 | 2533.6 → 1887.8 |
| Hybrid RRF | 900 / top-5 | 12 → 12 | 12 → 12 | 3738.2 → 2880.1 |

Shorter context is not automatically better: some settings lose evidence. Across
all 510 evaluated question/configuration/cutoff rows, no recorded context exceeds
4,096 tokens. At 900/top-10, vector and hybrid each retrieve complete evidence for
12/12 but deliver it for only 11/12. Both lose Helium's **7B parameter** evidence
during focusing, while retaining its training-token evidence. All other final
groups have equal aggregate retrieval and context coverage. The initial
implementation's 900/top-5 BM25 context covered 11/12; after the combined review
fixes, the final run covers 12/12. The two runs are both preserved.

The regressions are material. In the saved top-50 vector rankings, the smallest
prefix containing complete evidence changes as follows:

| Question and configuration | Original rank | Final rank | Missing evidence at the smaller cutoff |
| --- | ---: | ---: | --- |
| A2: Attention Table 2, 300 tokens | 2 | 19 | Transformer (big) row with both BLEU scores; labels alone are insufficient |
| M3: Helium, 300 tokens | 4 | 26 | 7B parameter statement |
| H4: H-Net efficiency, 300 tokens | 3 | 4 | Full 3.6× comparison with its direction |
| H2: H-Net routing, 600 tokens | 3 | 8 | Complete annotated threshold/initial-probability evidence |
| M2: Mimi quantization, 900 tokens | 3 | 10 | All requested quantizer/codebook/rate/bitrate facts together |

Table rows can still be separated from their headers, and section-preserving
chunks can separate facts previously contained in one larger passage. Changes to
the text also change vector and lexical rankings. These observations support
keeping the choices configurable; they do not establish a causal ablation or a
best production setting. Exact IDs, scores, selected passages, per-unit outcomes
and context counts are in [rankings.json](evaluation-final/rankings.json),
[results.csv](evaluation-final/results.csv) and
[summary.json](evaluation-final/summary.json).

**Refusal support is measured but deliberately limited.**

In every one of the 30 strategy/size/cutoff groups, all five audit unsupported
questions receive `insufficient_evidence`; none of the 12 answerable questions is
refused by the literal-constraint checks. These are repeated evaluations of the
same five and 12 questions, not 150 independent negative examples. Several
answerable queries still lack complete evidence despite passing the checks.
No general refusal-accuracy or hallucination-rate claim follows from this result.

The unsupported cases ask for Moshi p95 latency on iPhone/iOS, 70B-parameter H-Net
benchmarks, the original Transformer's MMLU accuracy, Moshi's November 2026 API
pricing, or a Moshi-versus-H-Net WMT2014 BLEU comparison. The supplied papers do
not report those requested facts. The saved
[iPhone CLI example](unsupported-iphone.json) returns explicit missing constraints.
Callers can add `EvidenceRequirement` values or repeated `--require` phrases for
constraints the automatic heuristic does not recognize. These checks operate on
normalized lexical phrases; they do not reason about negation, numeric relations
or whether the named facts jointly entail an answer.

**Files and cleanup.**

The [change inventory](changed-files.json) lists all 24 created/modified code,
test and existing documentation paths. [changes.diff](changes.diff) compares them
with the 25-file [baseline source archive](baseline-source.zip), because the
original Phase 2 source was already untracked in Git. No commit was made.

| Status | Files | Purpose |
| --- | --- | --- |
| Created | `src/retrieval/layout.py`, `text.py` | PDF geometry and shared text processing |
| Created | `src/retrieval/lexical.py`, `context.py`, `evidence.py` | BM25/RRF, bounded cited context and evidence requirements |
| Created | `scripts/evaluate_rag.py` | Reproducible comparison with the preserved audit |
| Created | `tests/rag/test_context.py`, `test_evidence.py`, `test_lexical.py`, `test_regressions.py` | Behavior, numeric evidence and audit regressions |
| Modified | `src/retrieval/chunking.py`, `extraction.py`, `pipeline.py` | Boundary chunks, section extraction and orchestration |
| Modified | `src/retrieval/config.py`, `models.py`, `index.py`, `cli.py` | Configuration, score/provenance records, shared store access and CLI |
| Modified | `tests/rag/test_chunking.py`, `test_extraction.py`, `test_integration.py`, `test_pipeline.py` | Existing contracts plus real-model latency evidence and review fixes |
| Modified | `README.md`, `docs/rag.md`, `.gitignore` | Commands, architecture, limitations and separate v2 database path |
| Created evidence | This review directory, including both evaluation runs, CSVs, JUnit reports, source archives, CLI results and verification/cleanup records | Assignment evidence and reproduction |

The full-project reference scan covered 85 reference-bearing files. Every Python
source, useful test, configuration, required PDF, existing report and experiment
was retained. The Phase 1 `tests/test_model.py` and `tests/groqtest.py` are intentional
manual Groq scripts, not abandoned code. The audit's scripts, figures and scratch
database are reproduction artifacts. The two evaluation runs record different
tested implementations and are not disposable duplicate results.

Only **31 generated `.pyc` files (373,826 bytes)** were deleted. For every file,
the corresponding `.py` source exists and the reference scan found no explicit
dependency on the bytecode file. All absolute paths were validated inside the
workspace before individual, nonrecursive `Remove-Item -LiteralPath` calls.
The exact deletion list and reasons are in [cleanup-results.json](cleanup-results.json);
the preceding scan is in [cleanup-plan.json](cleanup-plan.json). No source,
documentation, configuration, PDF, database, CSV or experiment evidence was deleted.
No reference updates were needed for bytecode removal.

**Actual verification results.**

| Check | Result | Evidence |
| --- | --- | --- |
| Initial complete configured pytest run, including integration | 90 passed; zero failures/errors/skips | [pytest-initial.xml](pytest-initial.xml) |
| Final complete configured pytest run after review fixes | 93 passed; zero failures/errors/skips; JUnit suite time 444.988 s | [pytest-final.xml](pytest-final.xml) |
| Ruff lint on RAG source/tests/evaluator | Passed, exit 0 | [quality-checks.json](quality-checks.json) |
| Ruff formatting check on the same targets | 31 files already formatted, exit 0 | [quality-checks.json](quality-checks.json) |
| `git diff --check` | Exit 0; only Windows LF/CRLF notices | [quality-checks.json](quality-checks.json) |
| Final retrieval evaluation | Completed; 510 rows, 30 groups, 120 extracted pages | [results.csv](evaluation-final/results.csv) |
| Baseline preservation and evaluated-source hashes | All 47 protected files and all 17 evaluated production modules match | [verification-final.json](verification-final.json) |

The complete configured pytest suite is `tests/rag`, including the three actual
PDF/index/retrieval integration presets when `--run-integration` is given. The
unchanged `pyproject.toml` excludes the two pre-existing manual Groq scripts, which
perform remote API calls at import/execution time; they were not run. The lint
targets cover the maintained RAG module, its tests and the new evaluator, not
preserved audit experiments or those manual scripts. Final code/tests are also
archived in [evaluation-final/source.zip](evaluation-final/source.zip). Reporting
and bytecode cleanup did not change the tested production code.

**Commands to reproduce and use the module.** Run from the repository root with
the existing environment and pinned model already cached. Full setup and model
cache instructions are in [docs/rag.md](../../../docs/rag.md).

```powershell
.venv\Scripts\python.exe -m retrieval extract
.venv\Scripts\python.exe -m retrieval ingest --preset 300
.venv\Scripts\python.exe -m retrieval ingest --preset 600
.venv\Scripts\python.exe -m retrieval ingest --preset 900
.venv\Scripts\python.exe -m retrieval retrieve "What are the theoretical and practical latency of Moshi full-duplex speech dialogue?" --preset 300 --strategy bm25
.venv\Scripts\python.exe -m retrieval search "How does H-Net learn chunk boundaries?" --preset 600 --strategy hybrid --top-k 5
.venv\Scripts\python.exe -m retrieval retrieve "What p95 latency does Moshi measure on an iPhone 15 Pro running iOS?" --preset 300 --strategy bm25 --max-context-tokens 2000
.venv\Scripts\python.exe scripts/evaluate_rag.py --output reports/rag/evaluation-new-run
.venv\Scripts\python.exe -m pytest --run-integration -q
.venv\Scripts\python.exe -m ruff check src/retrieval tests/rag scripts/evaluate_rag.py
.venv\Scripts\python.exe -m ruff format --check src/retrieval tests/rag scripts/evaluate_rag.py
```

Use a fresh evaluation output directory: an existing `results.csv` is never
overwritten by the evaluator. `--chunk-size`, `--overlap`, `--chunking` and
`--db-dir` select indexing settings and must match between ingestion and search.
`--strategy`, `--top-k`, `--bm25-k1`, `--bm25-b`, `--candidate-k` and
`--rrf-constant` are query settings and do not require another index.
`--max-context-tokens` controls `retrieve` context, and repeated `--require`
phrases add AND constraints. An ordinary refusal is a successful CLI result
(exit 0); input/storage failures are errors. Keep `data/chroma/` and the original
audit unchanged; reproducing the old implementation requires its source archive
in a separate checkout, not running the old audit scripts against v2 code.

**Remaining limitations and recommended next phase.** General OCR/math recovery,
merged table cells, complete table-header propagation, universal section
recognition and semantic refusal are unfinished capabilities. The PDFs themselves
also contain conflicting claims: Attention's EN-FR BLEU is 41.8 in Table 2 and
41.0 in prose, and H-Net's 3.6× data-efficiency wording is inconsistent. Both
statements remain visible; a future answer layer must expose the conflict.
MiniLM uses local 254-content-token windows with pooled embeddings for larger
chunks. This avoids silent truncation but can dilute a small relevant passage.
The 4,096-token budget uses the supplied tokenizer and excludes future system,
question and output-reservation costs; a generation model needs its own final
prompt budget. Context focusing and literal checks remain the most important
measured limits for a future answering layer.

The recommended next phase is a held-out retrieval and answerability evaluation,
with manual table/number annotations, broader unsupported cases, and focused
experiments on table-header/neighbor expansion and Helium evidence retention.
Use those results to select a production strategy and context policy before LLM
orchestration. No LLM orchestration, mock service or load-testing implementation
was started. This phase is ready for final review.
