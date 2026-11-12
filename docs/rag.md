# Research-paper ingestion and retrieval

This module validates and indexes exactly these supplied files:

| File | Paper | arXiv version | Physical PDF pages |
| --- | --- | --- | --- |
| `papers/attention_is_all_you_need.pdf` | Attention Is All You Need | 1706.03762v7 | 15 |
| `papers/moshi.pdf` | Moshi: a speech-text foundation model for real-time dialogue | 2410.00037v1 | 66 |
| `papers/dynamic_chunking.pdf` | Dynamic Chunking for End-to-End Hierarchical Sequence Modeling | 2507.07955v2 | 39 |

The manifest in `src/retrieval/catalog.py` pins each file's SHA-256, title, arXiv ID,
and version. Ingestion checks filenames, checksums, and the first-page arXiv stamp
before writing an index. Missing, changed, extra, or duplicated PDF files are errors.
The checksums identify the supplied bytes; another download of the same arXiv
version can have different bytes and is intentionally rejected. Updating the corpus
requires an explicit manifest review.

The current pipeline is `relay-rag-v2.1`. Its default database is `data/chroma-v2/`;
the v1 database in `data/chroma/` and the original audit reports remain intact.
Reingestion is required for the new extraction/chunking semantics. The previous
source, tests and guide are preserved in
[`baseline-source.zip`](../reports/rag/improvements-2026-11-11/baseline-source.zip).

## Setup

The implementation was developed with Python 3.12.2. Use the existing virtual
environment, or create one with Python 3.12. Run commands from the repository root.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c requirements.txt -e ".[dev]"
```

`pyproject.toml` pins the module's runtime dependencies, Pytest, and Ruff. The
existing `requirements.txt` supplies constraints for transitive dependencies; it
has not been rewritten. The package installs the `retrieval` and `relay` namespaces
from `src`. On Linux/macOS, replace `.venv\Scripts\python.exe` with `.venv/bin/python`.

Provision model files once if the following revision is not already cached. This
optional preparation step downloads model assets; it never uploads paper text.
The ingestion and search commands themselves operate with `local_files_only=True`
and fail clearly when the required snapshot is absent.

```powershell
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='sentence-transformers/all-MiniLM-L6-v2', revision='c9745ed1d9f207416be6d2e6f8de32d1f16199bf', allow_patterns=['*.json', '*.safetensors', 'vocab.txt'])"
```

The default Hugging Face hub cache is used. To use another hub cache, pass its path
as `cache_dir` to `snapshot_download` and `--model-cache` to ingestion/search. Supply
the hub cache directory, not an individual snapshot directory. A provisioned cache
can also be copied from another machine for offline setup.

## Commands

Inspect extraction without loading an embedding model. The command prints a JSON
summary; the Python extraction API exposes the actual page text and section spans.
Logs go to stderr. `--output` also writes the JSON result as UTF-8.

```powershell
.venv\Scripts\python.exe -m retrieval extract --output reports/rag/v2-extraction.json
```

Ingest and query the default 300-token / top-3 configuration:

```powershell
.venv\Scripts\python.exe -m retrieval ingest --preset 300 --output reports/rag/v2-ingestion-300.json
.venv\Scripts\python.exe -m retrieval search "Why are attention scores scaled by the square root of the key dimension?" --preset 300
.venv\Scripts\python.exe -m retrieval search "What is Moshi's theoretical latency?" --preset 300 --arxiv-id 2410.00037 --top-k 3
```

Prepare the other evaluation configurations in the same local database:

```powershell
.venv\Scripts\python.exe -m retrieval ingest --preset 600 --output reports/rag/v2-ingestion-600.json
.venv\Scripts\python.exe -m retrieval ingest --preset 900 --output reports/rag/v2-ingestion-900.json
.venv\Scripts\python.exe -m retrieval search "How does H-Net learn dynamic chunk boundaries?" --preset 600
.venv\Scripts\python.exe -m retrieval search "How does H-Net learn dynamic chunk boundaries?" --preset 900
```

| Preset | Maximum chunk tokens | Overlap tokens | Default retrieved chunks |
| --- | ---: | ---: | ---: |
| 300 | 300 | 50 | 3 |
| 600 | 600 | 50 | 4 |
| 900 | 900 | 50 | 5 |

Configured overlap stays at 50 across the presets. Boundary alignment can reduce
the actual overlap, and sections do not overlap. These are candidate configurations, with
no quality ranking implied. `--chunk-size`, `--overlap`, and `--top-k` override
preset values. Overlap must be nonnegative and less than chunk size; chunk size,
top-k, and `--batch-size` must be positive integers. Changing chunk size/overlap
requires ingestion of that configuration before querying it. `--chunking boundary`
is the default; `--chunking fixed` retains token-window behavior for comparisons.
Changing chunking mode also requires ingestion. Top-k is query-only
and reuses the same index. Search caps top-k at the available matching chunk count.

```powershell
.venv\Scripts\python.exe -m retrieval ingest --chunk-size 600 --overlap 80 --batch-size 8
.venv\Scripts\python.exe -m retrieval search "Explain Inner Monologue" --chunk-size 600 --overlap 80 --top-k 4
```

`--papers-dir` defaults to `papers`; `--db-dir` defaults to `data/chroma-v2`. Chroma data
is local and git-ignored. Different chunk, model, or recorded runtime settings have
separate fingerprinted collections. Ingestion retries reuse stored deterministic
IDs and embed only missing chunks. There is no automatic deletion of collections;
use a separate `--db-dir` for a fresh experiment.

Select retrieval explicitly; the default remains `vector`. BM25 and hybrid search
use the same Chroma documents and source metadata. Strategy, `--bm25-k1` (1.5),
`--bm25-b` (0.75), `--candidate-k` (50), and `--rrf-constant` (60) are query settings
and do not require another index. Hybrid combines the top candidates from vector
and BM25 with equal-weight reciprocal-rank fusion. It is not automatically selected
for numerical queries or enabled everywhere.

```powershell
.venv\Scripts\python.exe -m retrieval search "What are the theoretical and practical latency of Moshi full-duplex speech dialogue?" --preset 300 --strategy bm25
.venv\Scripts\python.exe -m retrieval search "How does H-Net learn chunk boundaries?" --preset 600 --strategy hybrid --top-k 5
.venv\Scripts\python.exe -m retrieval retrieve "What p95 latency does Moshi measure on an iPhone 15 Pro running iOS?" --strategy bm25 --max-context-tokens 2000
.venv\Scripts\python.exe -m retrieval retrieve "What latency does Moshi report?" --strategy bm25 --arxiv-id 2410.00037 --require "160 ms" --require "200 ms"
```

`search` returns ranked neighbors. `retrieve` additionally returns bounded context,
the selected passages and an evidence assessment. Missing requested constraints
produce `evidence.refused=true` and `status=insufficient_evidence`, with explicit
missing labels. A successful literal check yields `candidate_evidence`, not an
assertion that a complete answer is entailed. Both outcomes use exit status 0;
refusal is a normal result, while invalid input/storage errors use status 1.

Use `python -m retrieval --verbose ...` for a traceback and debug logs when diagnosing
an error. Expected validation, extraction, embedding, and storage errors exit with
status 1; invalid command syntax exits with status 2. Neither logs nor embedding
errors intentionally print complete paper text.

## Architecture and reusable interfaces

```text
Fixed PDF manifest -> validation -> page/section extraction
    -> WordPiece chunks + source spans -> local MiniLM windows
    -> normalized pooled embeddings -> persistent Chroma collection
Query -> vector / BM25 / optional rank fusion -> cited passages
    -> query-focused bounded context -> explicit evidence-constraint assessment
```

| Module | Responsibility |
| --- | --- |
| `catalog.py` | Exact corpus identities, checksums, and version validation |
| `layout.py`, `extraction.py` | PDF geometry, numeric text, physical pages, sections and extraction warnings |
| `chunking.py`, `text.py` | Boundary-aware/fixed chunks, normalization and source offsets |
| `embeddings.py` | Pinned SentenceTransformer tokenizer and CPU inference |
| `index.py` | Local Chroma storage, readiness checks, and semantic search |
| `lexical.py` | Local BM25 and configurable reciprocal-rank fusion |
| `context.py` | Passage selection, overlap deduplication, exact budgets and citation slicing |
| `evidence.py` | Explicit evidence constraints and conservative refusal support |
| `pipeline.py` | Ingestion/retry and retrieval orchestration |
| `models.py`, `config.py`, `errors.py` | Typed records, validated settings, and public error types |
| `cli.py` | JSON command-line interface |

PyMuPDF reads text spans in geometric order. Extraction normalizes Unicode with
NFKC and collapses whitespace within lines. Superscripts become explicit `^{...}`
before normalization; alphabetic line-end hyphenation is joined within text blocks.
The rotation filter targets the arXiv margin stamp and keeps rotated body/figure
labels. Only a matching physical-page footer number is removed near the bottom.
Table detection supplies geometry, while original text spans supply cell content
to avoid the table parser's decimal-point reordering. Rows have `|` separators;
ambiguous or spanning columns produce `table_layout_warning` issues. No missing
cell values are inferred. Fractions and general two-dimensional equations are not
reconstructed; recognized uncertain math produces `math_layout_warning` issues.
`PageText.regions` retains block types, offsets and PDF bounding boxes.

Section recognition prefers outline titles on their bookmarked page, favoring an
actual numbered heading over a matching diagram label. Table regions cannot become
headings. Standalone section numbers are joined only with plausible heading geometry;
already-numbered headings do not acquire the preceding table value. Strict typography
and text heuristics provide a fallback for PDFs without outlines. The recognized section
carries to the next page. Unrecognized front matter has `section=None`; no section
is invented from a page number alone.

Blank pages produce logged `empty_page` issues. Repeated normalized page text
produces `duplicate_page` issues containing the original physical page reference.
Blank and duplicate pages do not enter chunking. A corrupt, encrypted, wholly
unreadable PDF or page extraction exception aborts ingestion; there is no silent
partial-corpus indexing. Extraction completes for all papers before any store write.

Chunks use the pinned MiniLM WordPiece tokenizer, excluding special tokens. Boundary
chunks stay within a section (carrying an otherwise orphaned parent heading into
its child), prefer complete sentences, preserve a table as one
unit when it fits, and split long tables at rows where feasible. They can cross
pages within a section and never cross papers. Fixed mode permits page/section
crossings as before. Source spans map
each piece back to its exact extracted page/section. Final windows can be shorter
than the configured maximum. Token offsets determine overlap; a cut inside a
WordPiece can change the substring's tokenization, so returned text is always
recounted. Boundary mode avoids cuts between alphanumeric characters and rejects a
chunk size too small for one complete word. Oversized sentences may still split at
word boundaries; this is not a semantic discourse parser.

Each Chroma record stores the original extracted chunk text, document ID, paper
title, arXiv ID, version, PDF checksum, relative source filename, versioned source
URL, token/character positions, content hash, first/last page, exact page list,
sections, and per-page/section character spans. Lists and nested source spans are
serialized as JSON strings for portable Chroma metadata. `page_number` aliases the
first physical page; `page_numbers_json` is authoritative when pages are noncontiguous.

Within one paper, identical normalized chunks are indexed once, with discarded
locations recorded in the ingestion report. Identical passages across papers are
detected but both are kept to preserve attribution. PDF/page/chunk hashes ignore
whitespace only where documented; no fuzzy or semantic deduplication is performed.

MiniLM's configured sequence limit is 256 tokens, including two BERT special tokens.
All three requested chunk sizes exceed that limit. Each chunk or query is therefore
split into nonoverlapping windows of at most 254 content token IDs. The local
SentenceTransformer processes every window. Window vectors are normalized, averaged
with content-token-count weights, and normalized again into one 384-dimensional
vector. Token IDs enter the model directly, without decoding and re-tokenizing.
The same procedure is used for queries and documents. Long inputs are never silently
truncated to the first 256 tokens.

Chroma uses cosine HNSW search with explicit vectors, `embedding_function=None`, and
anonymized telemetry disabled. It cannot fall back to its default embedding download.
The pipeline uses deterministic IDs and `upsert`; unchanged retries skip embedding
work. A collection is marked incomplete before writes and becomes searchable only
after its stored ID set matches the expected corpus chunks. A failed batch leaves
the collection unavailable for search; rerunning ingestion resumes missing rows.
Unexpected rows cause an error instead of silently mixing corpora. This is a
single-writer module; concurrent ingestion/read consistency is outside this phase.

```python
from pathlib import Path

from retrieval.config import PRESETS
from retrieval.pipeline import RetrievalPipeline, build_context

rag = RetrievalPipeline(
    papers_dir=Path("papers"),
    db_dir=Path("data/chroma-v2"),
    config=PRESETS[600],
)
report = rag.ingest()
hits = rag.search("How does Moshi handle overlapping speech?", arxiv_id="2410.00037")
for hit in hits:
    print(hit.citation, hit.source_url, hit.score)
    print(hit.text)

# Optional local context preparation. This performs no LLM call.
context = build_context(hits, rag.embedder.tokenizer, max_tokens=3000,
                        query="How does Moshi handle overlapping speech?")
```

`SearchHit.to_dict()` provides serializable text, sources, physical pages, sections,
versioned citation, URL with a PDF page fragment, and an explicit `score_type`:
`cosine_similarity`, `bm25` or `rrf`. `distance` is nullable for hits without a vector
score. Ranking scores are not factual-confidence probabilities. BM25 performs no
query embedding; the pipeline still loads the cached model/tokenizer to validate
the collection descriptor. Its in-memory lexical index is rebuilt from the ready
Chroma documents per request, appropriate for this small fixed corpus.

`build_context` remains available from `retrieval.pipeline`. Without a query, it
packs complete cited hits and skips oversized hits so later evidence can fit.
With a query, long hits are focused into complete sentence windows or table rows
using local lexical ranking. Budget shares redistribute space unused by short hits;
whole passages are restored when spare capacity permits. Duplicate/fully contained
passages from the same paper are omitted. `select_context` also exposes selected
hits, exact token counts and omitted IDs. Every clipped passage has adjusted source
spans, physical pages, a parent chunk ID and paper-relative character offset.
Final counts include citation headers, ordinals and separators. No entire-paper context is
constructed or sent to an LLM. Budget counts use the supplied tokenizer; the Relay
application also checks a conservative whole-prompt bound in `relay/budget.py`.

`EvidenceRequirement` accepts a label, alternative literal phrases (OR), and an
optional paper ID. Multiple requirements use AND semantics. `retrieve` also
recognizes some high-specificity query constraints: named papers/models, acronyms,
percentiles, certain hardware names, parameter-count phrases and explicit dates.
Checks apply to the actual bounded context, including paper attribution. They
are deliberately limited: absence from retrieved context does not prove absence
from the corpus, and passing literal checks does not prove semantic sufficiency.
Use explicit requirements for facts the automatic heuristic cannot recognize.

## Reproducibility, tests, and evaluation preparation

Document IDs include the exact paper/version and PDF hash. Chunk IDs additionally
include pipeline revision, tokenizer revision, chunk settings, token position, and
text. Collection fingerprints include the manifest, pipeline revision, chunk settings,
embedding strategy/revision, and recorded runtime dependency versions. Absolute file
paths and top-k do not affect IDs. Increment `PIPELINE_VERSION` when changing
extraction, chunking, metadata, or embedding
semantics so earlier collections cannot be reused with changed behavior.
Ingestion preserves fixed paper/chunk order. Embedding inference runs in evaluation
mode on CPU, with seed 0, deterministic
PyTorch algorithms, and one PyTorch thread. These PyTorch settings affect the
hosting process. Chroma HNSW uses one thread. Reports include configuration,
fingerprint, dependencies, per-paper counts/issues, and new/reused/duplicate counts.
Within one pipeline instance, extraction is cached after validation; every reuse
still rechecks PDF checksums. A new process performs extraction again.

```powershell
# Offline unit suite, including actual PDF extraction and temporary Chroma DBs.
.venv\Scripts\python.exe -m pytest -q

# Full suite, adding cached-model inference and retrieval for all three presets.
.venv\Scripts\python.exe -m pytest -q --run-integration

# Run only the real-model integration tests.
.venv\Scripts\python.exe -m pytest -q --run-integration -m integration

.venv\Scripts\python.exe -m ruff check src/retrieval tests/rag scripts/evaluate_rag.py
.venv\Scripts\python.exe -m ruff format --check src/retrieval tests/rag scripts/evaluate_rag.py
```

The default suite uses explicitly synthetic embeddings for storage/orchestration
tests, generated PDFs for failures/duplicates, and all supplied PDFs for extraction.
It makes no semantic-quality claim based on those synthetic vectors. Integration
tests require the pinned local model; when requested, missing assets fail the tests
instead of being silently skipped. Tests block Python socket connections, covering
offline operation. Test database files are isolated under Pytest temporary directories.
The pre-existing `tests/test_model.py` and `tests/groqtest.py` are manual scripts that
call Groq at import/execution time. They are excluded by the current
`testpaths = ["tests/rag", "tests/relay"]` setting.

The integration checks compare short-input embeddings with standard
SentenceTransformers output, verify that long-input suffixes affect embeddings, and
check cited retrieval across all three presets. The Moshi regression now requires
both numerical latency values in correctly attributed BM25 top-3 evidence.
Other tests cover decimal/exponent retention, table rows, section false positives,
rotated labels, numerical sentence boundaries, lexical/fusion behavior, context
budgets, citation slicing and missing evidence constraints.

Run the existing audit's 12 answerable and five unsupported questions through all
three strategies and chunk configurations with a new output directory:

```powershell
.venv\Scripts\python.exe scripts/evaluate_rag.py --output reports/rag/evaluation-new-run
```

The evaluator uses the production search/context/evidence functions, checks source
alignment before retrieval, blocks Python sockets and saves raw rankings, exact
passages, `results.csv`, context coverage, refusal outcomes and a baseline comparison.
It will not overwrite an existing `results.csv`. Presentation-only annotation
adaptations are recorded. Results are complete annotated evidence coverage across
returned spans, not answer-generation accuracy. This is a small diagnostic set,
not held-out validation; the original audit is preserved. See the
[implementation review](../reports/rag/improvements-2026-11-11/review.md) for actual results.

## Known limitations

- Extraction does not perform OCR or reconstruct general equations. Table row
  geometry improves association but merged cells, complex headers, two-column
  layouts and figure reading order remain imperfect. Superscripts are represented
  explicitly; subscripts and fractions can still need the original PDF. Line-end
  joining can remove a genuine compound-word hyphen. Empty-page detection cannot
  identify every figure whose only extractable text is a caption or header.
- Section detection uses bookmarks and layout/text heuristics, not a document-layout
  model. Some section names may be absent or imperfect. Citations always use
  physical PDF pages, which can differ from printed page labels.
- Oversized sentences/table rows and fixed-mode windows can split evidence. Long
  tables may lose header context when split or focused into a limited budget.
  Pooling every local window avoids
  data loss from truncation but cannot model interactions across the full 600/900
  tokens in one transformer pass. It may dilute a small relevant passage inside a
  large chunk. No size or pooling strategy is claimed superior without evaluation.
- Duplicate pages and within-paper duplicate chunks retain their first indexed
  location; alternative occurrences are available in the ingestion report. Small
  textual changes and approximate duplicates remain indexed.
- HNSW is approximate. Fixed ordering/settings and sorted returned ties improve
  repeatability, but identical neighbor membership or bitwise floating-point output
  across dependency, CPU, or operating-system changes is not guaranteed. Changing
  recorded dependencies creates another collection. Index manifests should be
  treated as trusted local data, and ingestion should have one writer at a time.
- Vector search still returns neighbors for unsupported questions. The separate
  evidence assessment provides explicit, limited refusal support; it is not a
  calibrated entailment model. Lexical overlap and rank fusion can introduce
  regressions. This retrieval module has no cross-encoder or contradiction resolver;
  the separate `relay` package implements generation and stand-in load experiments.
- The PDFs contain conflicting statements (Attention EN-FR BLEU 41.8 in Table 2
  versus 41.0 in prose, and H-Net's 3.6× data-efficiency wording). Extraction keeps
  both statements. The answer layer must cite the requested source and expose
  conflicts rather than silently resolve them.

The retrieval module ends at cited retrieval and bounded context preparation. The
current application uses BM25/600/top-4 and is documented in [README.md](../README.md).
Phase 5.4 also uses `infer_answer_parts()` and `assess_answer_coverage()` from
`evidence.py` to check recognized multipart quantities against validated claim text
and its own quotations. This is separate from the retrieval evidence gate and is
not unrestricted semantic entailment. Unrecognized coordinated requests fail safely.
See [final submission review](../reports/final-evaluation/final-review-2026-11-12.md)
for current verification, historical evidence boundaries, and remaining limitations.
