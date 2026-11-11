# The Relay

Phase 2 implements local research-paper ingestion and vector/BM25 retrieval in
`src/retrieval`. It accepts exactly the three supplied, version-pinned PDFs in
`papers/` and returns passages with paper, section, and physical PDF page citations.

See [the RAG module guide](docs/rag.md) for setup, commands, architecture,
reproducibility details, evaluation configurations, and limitations.
The audit-driven changes, measured comparisons and verification record are in
[the implementation review](reports/rag/improvements-2026-11-11/review.md).
The v2 database defaults to `data/chroma-v2/`; the v1 database and audit are preserved.

```powershell
.venv\Scripts\python.exe -m pip install -c requirements.txt -e ".[dev]"
.venv\Scripts\python.exe -m retrieval extract
.venv\Scripts\python.exe -m retrieval ingest --preset 300
.venv\Scripts\python.exe -m retrieval search "How does scaled dot-product attention work?" --preset 300
.venv\Scripts\python.exe -m retrieval retrieve "What are Moshi's theoretical and practical latency?" --preset 300 --strategy bm25
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q --run-integration
.venv\Scripts\python.exe -m ruff check src/retrieval tests/rag scripts/evaluate_rag.py
.venv\Scripts\python.exe -m ruff format --check src/retrieval tests/rag scripts/evaluate_rag.py
```

The embedding model must already be cached; the guide includes its pinned download
command. All inference runs locally on CPU. This module does not call an LLM or
implement the application, API, queue, or answer-generation layer.
