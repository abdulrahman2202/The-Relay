# The Relay

The Relay is a Python terminal research assistant for three supplied, version-pinned
papers: *Attention Is All You Need*, *Moshi*, and *Dynamic Chunking for End-to-End
Hierarchical Sequence Modeling*. It combines local PDF ingestion, vector/BM25/hybrid
retrieval, real Groq tool calling, streamed evidence-grounded answers, citations, and
refusal behavior.

It also ships a deterministic local FastAPI stand-in and a load harness for exercising
queues, rate limits, overload, retries, and budget exhaustion without an API key.

## Quick start

Requirements: Python 3.12 (developed on 3.12.2). Run every command from the repository
root. The examples use PowerShell; on macOS/Linux replace `.venv\Scripts\python.exe`
with `.venv/bin/python`.

### 1. Install

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c requirements.txt -e ".[dev]"
```

### 2. Cache the pinned embedding model (once)

Retrieval uses `sentence-transformers/all-MiniLM-L6-v2` at a fixed revision and does not
download it on demand. Skip this step if that revision is already in your Hugging Face
cache.

```powershell
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='sentence-transformers/all-MiniLM-L6-v2', revision='c9745ed1d9f207416be6d2e6f8de32d1f16199bf', allow_patterns=['*.json', '*.safetensors', 'vocab.txt'])"
```

See [docs/rag.md](docs/rag.md) for offline cache copying and `--model-cache` usage.

### 3. Build the local index

The PDFs in `papers/` are checksum-pinned. Ingestion validates them and writes a local
Chroma database to `data/chroma-v2/` (git-ignored). Re-running ingestion resumes
missing chunks instead of re-embedding everything.

```powershell
.venv\Scripts\python.exe -m retrieval extract
.venv\Scripts\python.exe -m retrieval ingest --preset 600
```

Check retrieval without calling any LLM:

```powershell
.venv\Scripts\python.exe -m retrieval retrieve "What are Moshi's theoretical and practical latency?" --preset 600 --strategy bm25
```

`retrieve` returns ranked passages, a bounded context, and an evidence assessment.
`search` returns only ranked neighbors.

### 4. Run the research assistant (live Groq)

Create `.env` from the example and put your key in it. `.env` is git-ignored; never
commit it.

```powershell
Copy-Item .env.example .env
# Edit .env: set GROQ_API_KEY=... (optionally change GROQ_MODEL)
```

```powershell
.venv\Scripts\python.exe -m relay
```

Type a question at the `You:` prompt, or `exit` to leave. One-shot and diagnostic modes:

```powershell
.venv\Scripts\python.exe -m relay --question "What are Moshi's theoretical and practical latency?"
.venv\Scripts\python.exe -m relay --question "What are Moshi's theoretical and practical latency?" --json
.venv\Scripts\python.exe -m relay --diagnostics
```

Defaults are BM25 retrieval, 600-token chunks, top-4 passages, and a 3000-token evidence
budget. `--json` requires `--question` and cannot be combined with `--diagnostics`.
Run `python -m relay --help` for all options (preset, strategy, timeouts, budgets,
database/model paths).

## Test it

The default suite is offline: it uses synthetic embeddings, generated PDFs, and temporary
Chroma databases, and it blocks network sockets. No Groq key is needed.

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected on the supplied environment: `276 passed, 5 skipped`. The five skips are
cached-model integration cases; run them when the pinned model is cached:

```powershell
.venv\Scripts\python.exe -m pytest -q --run-integration -m integration
```

Lint and format checks:

```powershell
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m ruff format --check src tests scripts
```

Validate the recorded load results:

```powershell
.venv\Scripts\python.exe -c "from pathlib import Path; from relay.loadtest import read_results_csv; print('Validated rows:', len(read_results_csv(Path('results/results.csv'))))"
```

Do **not** collect `tests/test_model.py` or `tests/groqtest.py`: they are legacy manual
scripts that call Groq on import/execution and are intentionally outside `testpaths`.

## Offline demo and load testing

Start the deterministic stand-in. It requires no API key and never calls Groq:

```powershell
.venv\Scripts\python.exe -m relay.mock --scenario normal --host 127.0.0.1 --port 8099
```

Scenarios: `normal`, `slow`, `temporary_failure`, `rate_limit`, `budget_exhausted`,
`timeout`, `streaming`, `overloaded`.

Run a quick in-process load scenario without writing files:

```powershell
.venv\Scripts\python.exe -c "import asyncio; from relay.loadtest import run_load_scenario; from relay.mock.config import scenario_config; r=asyncio.run(run_load_scenario(name='demo', config=scenario_config('normal'), requests=5)); print(r.summary)"
```

The full Phase 4 experiment reproduces all recorded scenarios. It rewrites
`results/results.csv` and `reports/phase4/load-test-summaries.json`, so run it only in a
disposable copy if you want to keep the submitted artifacts:

```powershell
.venv\Scripts\python.exe scripts/run_phase4_experiments.py --skip-real
```

All stand-in measurements are simulated. The in-process transport also buffers streamed
responses, so its recorded first-token time is not a real network TTFT.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Configuration error. Check .env, GROQ_API_KEY...` | Set a valid `GROQ_API_KEY` in `.env` or the environment. |
| Missing model/snapshot error during ingest or retrieval | Run the `snapshot_download` command in step 2, or pass `--model-cache`. |
| Collection not found / not ready | Run `python -m retrieval ingest --preset 600` before querying. |
| PDF validation error | Use the exact supplied PDFs in `papers/`; other downloads of the same arXiv version can have different bytes. |
| `--json requires --question` | Pass a question, or drop `--json`. |
| Integration tests skip | Add `--run-integration` and ensure the pinned model is cached. |

## Project layout

```text
papers/            Three checksum-pinned source PDFs
src/retrieval/     Extraction, chunking, embeddings, Chroma index, BM25/hybrid, evidence
src/relay/         Terminal assistant, Groq client, citations, budgets, mock service, load harness
tests/rag/         Offline retrieval tests
tests/relay/       Offline assistant, mock, reliability, and load tests
scripts/           Evaluation, calibration, and Phase 4 experiment scripts
reports/           Evaluation reports and preserved evidence
results/           Recorded load-test CSV/JSONL
docs/rag.md        Retrieval design, configuration, reproducibility, and limitations
```

## Further reading

- [Retrieval guide](docs/rag.md) — exact paper hashes, chunk presets, embedding strategy,
  index fingerprints, and retrieval limitations.
- [Final review and verification](reports/final-evaluation/final-review-2026-11-12.md) —
  reproduction commands, historical source revisions, and known limitations.
- [Two-page assignment report](reports/final-evaluation/final-assignment-report.pdf) and
  [submission readiness](reports/final-evaluation/submission-readiness.md).

Commands in this README are reproduction instructions. Live Groq calls require your own
key and are not part of the offline test suite.
