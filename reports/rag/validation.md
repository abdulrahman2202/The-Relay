# Phase 2 validation record

Executed in the existing Windows environment with Python 3.12.2 and the pinned
local `all-MiniLM-L6-v2` model. No remote embedding or LLM service was used.

| Check | Observed result |
| --- | --- |
| `python -m pytest -q --run-integration` | **59 passed** in 200.01 seconds |
| `python -m ruff check src/retrieval tests/rag` | All checks passed |
| `python -m ruff format --check src/retrieval tests/rag` | 21 files already formatted |
| `git diff --check` | Exit status 0 |
| Supplied PDF extraction | 120 pages; no empty pages, duplicate pages, or extraction failures |
| Default persistent ingestion | 380 chunks stored; collection verified ready |

Commands used `.venv\Scripts\python.exe`. The full test suite includes real local
inference and Chroma retrieval for all three requested presets (300/3, 600/4,
900/5), along with unit tests for extraction errors, source metadata, overlap,
duplicates, interrupted ingestion, persistence, filters, and bounded context.
The tests block Python socket connections. Synthetic unit-test vectors are not
used in the default persistent index.

The default index is in `data/chroma/` (git-ignored), with collection name
`relay_c7913dc6e7727636bf86bbe6bb8f767e`. The saved
[ingestion report](ingestion-300.json) records the complete configuration,
fingerprint, PDF/model revisions, runtime dependencies, and these counts:

| Paper | Pages | Indexed chunks |
| --- | ---: | ---: |
| Attention Is All You Need v7 | 15 | 38 |
| Moshi v1 | 66 | 192 |
| Dynamic Chunking v2 | 39 | 150 |
| Total | 120 | 380 |

The 600/900 configurations were exercised in isolated test databases; their
persistent project collections can be created with the documented ingestion commands.

## Observed retrieval limitation

[The saved CLI search](retrieval-300.json) asks:

> What are the theoretical and practical latency of Moshi full-duplex speech dialogue?

The 300-token/top-3 configuration returned Moshi passages citing page 1, pages 6–7,
and page 2. These passages discuss the topic but do **not** contain the requested
160 ms theoretical / 200 ms practical values from the abstract on page 1.
This is an answer-coverage miss, even though the paper/page smoke assertion passes.
No answer-generation or factual-accuracy success is claimed for this example.

The engineering checks establish that the pipeline works, retains provenance,
avoids silent embedding truncation, and supports the requested configurations.
The small page-based smoke set does not establish retrieval quality or a preferred
configuration. A later evaluation needs answer-bearing passage annotations,
unanswerable queries, citation checks, and measured retrieval/context costs.

See the [module guide](../../docs/rag.md) for exact setup and execution commands,
architecture, reproducibility policy, and other limitations.
