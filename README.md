# The Relay

The Relay is a Python terminal research assistant for exactly three supplied,
version-pinned papers. It combines local PDF ingestion and vector/BM25/hybrid
retrieval with real Groq tool calling, evidence-grounded streaming, citations,
refusal, and optional failure diagnostics. A separate local FastAPI stand-in and
load harness demonstrate queues, limits, overload, retries, and budget exhaustion.

Start with the [two-page report draft](reports/final-evaluation/final-assignment-report.pdf),
[submission readiness](reports/final-evaluation/submission-readiness.md), and
[final review and verification](reports/final-evaluation/final-review-2026-11-12.md).
Original evaluation results and later manual observations remain separate.

## Setup

Run from the repository root with Python 3.12 (development environment: 3.12.2).
Use the existing virtual environment or create one, then install the pinned project
and development dependencies. Package installation may require network access;
no installation or model download was performed during finalization.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c requirements.txt -e ".[dev]"
```

The [RAG guide](docs/rag.md) documents the exact paper hashes, embedding-model revision,
cache provisioning, CPU execution, chunk presets, and index fingerprints. Retrieval
requires the pinned MiniLM assets already cached; it does not download on demand.
The current database defaults to `data/chroma-v2/`. Prepare the application preset:

```powershell
.venv\Scripts\python.exe -m retrieval extract
.venv\Scripts\python.exe -m retrieval ingest --preset 600
.venv\Scripts\python.exe -m retrieval retrieve "What are Moshi's theoretical and practical latency?" --preset 600 --strategy bm25
```

These commands use local PDFs and embeddings. Preserve existing databases; use
`--db-dir` with a fresh directory for separate experiments. The historical RAG
comparison and its limitations are in the [implementation review](reports/rag/improvements-2026-11-11/review.md).

## Research assistant — real Groq calls

For live use only, set `GROQ_API_KEY` privately in the environment or in an untracked
`.env`; `.env.example` shows the required names. Keep an existing `.env` intact.
The default `GROQ_MODEL` is `openai/gpt-oss-20b`. Do not include credentials in a
submission. The following commands make real requests for research questions;
they were **not run during finalization**.

```powershell
.venv\Scripts\python.exe -m relay
.venv\Scripts\python.exe -m relay --question "What are Moshi's theoretical and practical latency?"
.venv\Scripts\python.exe -m relay --diagnostics
```

Type `exit` to leave. Defaults are BM25, 600-token chunks, top-4, and a 3000-token
evidence ceiling. `--json` requires `--question` and cannot be combined with
`--diagnostics`. Failed turns keep empty final answer/claim fields; already displayed
partial text is explicitly marked incomplete. Diagnostics can show rejected quotes,
source IDs, the last valid claim, malformed suffix, unsupported numbers, and missing
parts, with bounded/redacted display.

Phase 5.4's prompt `relay-phase3-v3` asks for exact quotations before claims and
structured examples for tables, conflicts, captions, and escaped formulas. A clean
completion marker and bounded deterministic multipart coverage are required.
Unrecognized coordinated questions fail safely; single questions outside that grammar
retain citation validation. These checks do not establish unrestricted factual entailment.

## Offline stand-in and reproducibility

The stand-in requires no API key and never calls Groq:

```powershell
.venv\Scripts\python.exe -m relay.mock --scenario normal --host 127.0.0.1 --port 8099
```

The [final review](reports/final-evaluation/final-review-2026-11-12.md) lists reproduction
commands and historical source revisions. Some experiment scripts write fixed paths;
run them only in a disposable copy, not over the submitted reports. Stand-in measurements
are simulated, and its in-process transport buffers streaming responses.

## Local verification

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m ruff format --check src tests scripts
.venv\Scripts\python.exe -c "from pathlib import Path; from relay.loadtest import read_results_csv; print('Validated rows:', len(read_results_csv(Path('results/results.csv'))))"
```

Default pytest collection is `tests/rag` and `tests/relay`. Five cached-MiniLM
integration cases require `--run-integration`; they are excluded by default. Automated
fixtures block external sockets. The legacy `tests/test_model.py` and `tests/groqtest.py`
make Groq calls on import/execution and must not be included in offline test collection.
An optional integration run, when needed and with the pinned local cache present, is:

```powershell
.venv\Scripts\python.exe -m pytest -q --run-integration -m integration
```

See the final review for the exact checks actually executed. This README's commands
are reproduction instructions, not a claim that every command was run.
