# Phase 4 Completion Status

- Repository: `C:\Programming\The-Relay`
- Date: 2026-11-11
- Scope: Phase 4 only: deterministic mock model service, bounded queue/retry manager, real-Groq calibration, simulated load experiments, required result artifacts, tests, and lint.
- Model used for real calibration: `openai/gpt-oss-20b`

## Status summary

| Requirement | Status | Evidence |
| --- | --- | --- |
| A. Mock model service | COMPLETE | FastAPI service with Groq/OpenAI-shaped JSON and SSE, deterministic scenarios, generated in `src/relay/mock` |
| B. Bounded queue and retry manager | COMPLETE | `src/relay/reliability.py` with concurrency cap, bounded waiting room, queue timeout, capped retries and retry-after handling |
| C. Real calibration | COMPLETE | 10 real Groq requests in `reports/phase4/calibration/real-groq-calibration.json` |
| D. Load testing | COMPLETE | Steady, burst and overload scenarios plus raw and summarized evidence |
| E. Rate-limit and budget behavior | COMPLETE | Per-minute limits, daily request/token budgets, `429` with retry metadata |
| F. Retry behavior experiments | COMPLETE | Recovery, retry-storm and non-retryable budget scenarios |
| G. Required CSV and raw outputs | COMPLETE | `results/results.csv` (283 validated rows) and `results/phase4/raw/*.jsonl` |
| H. Automated verification | COMPLETE | `185 passed, 5 skipped`; Ruff clean |

All load and retry measurements are simulated by the deterministic mock service. Only the 10 calibration rows are real Groq observations. The report keeps those categories separate throughout.

## What was built

### Mock model service

`src/relay/mock` is a local FastAPI stand-in for the Groq chat-completions surface. It never imports or calls Groq.

- `config.py` defines `MockConfig` and eight named scenarios: `normal`, `slow`, `temporary_failure`, `rate_limit`, `budget_exhausted`, `timeout`, `streaming`, `overloaded`.
- `gate.py` implements a semaphore-based bounded admission gate with a queue size limit and queue timeout.
- `accounting.py` implements a per-minute sliding window, daily request budget, daily token budget, counters, and response headers.
- `service.py` implements:
  - `POST /v1/chat/completions` for normal, streaming and error behavior.
  - `GET /health`, `GET /metrics`, `POST /admin/reset`.
  - OpenAI/Groq-shaped completion and chunk payloads, including usage metadata and `finish_reason`.
  - SSE streaming with incremental content chunks.
  - `x-mock-simulated: true` on simulated responses and scenario telemetry headers.
  - `x-mock-scenario` request override for per-request scenario selection.
  - Deterministic failures by request number, interval, or seeded probability.
  - `429` rate-limit responses with `retry-after` and rate-limit headers.
  - `503` retryable failures, `504` timeout responses, and queue rejection/timeout responses.
  - Queue wait and active-request headers for measurement.
- `__main__.py` runs the service with `python -m relay.mock`; `relay-mock` is registered as a script entry.

The mock delay defaults to `650 ms` processing, `20 ms` per streaming chunk and a `56`-token input overhead. These are calibration values, not claims that the real service is exactly reproducible.

### Reliability manager

`src/relay/reliability.py` provides an in-process request manager, not a distributed queue.

- Caps concurrent operations with `max_concurrency`.
- Bounds waiters with `max_queue_size`; a full waiting room is rejected immediately.
- Applies `queue_timeout_seconds` to waiting requests.
- Caps attempts with `max_attempts`.
- Retries only results explicitly marked retryable.
- Honors `retry-after` when it is within `max_retry_after_seconds`; otherwise gives up instead of sleeping indefinitely.
- Uses bounded exponential backoff with optional deterministic jitter.
- Returns classified outcomes instead of re-raising operation exceptions.

### Load harness

`src/relay/loadtest.py` drives the FastAPI app through `httpx.ASGITransport`, so the experiments are offline.

- Sends concurrent load and measures wall time.
- Measures streaming time-to-first-token (TTFT) and total latency.
- Reads queue wait from mock response headers.
- Computes p50, p95 and p99 percentiles with explicit sample counts.
- Writes the exact Phase 4 CSV schema and raw JSONL evidence.
- Validates source, status and answer-grade values before writing, and validates the CSV when reading it back.

## Real Groq calibration

The calibration script made a modest number of real requests and did not deliberately exhaust the free-tier quota.

| Observation | Value |
| --- | --- |
| Requested real calls | 10 |
| Successful | 9 |
| Rate-limited | 0 |
| Timeouts | 0 |
| Errors | 1 (deliberate invalid-model probe) |
| Input tokens | 710 |
| Output tokens | 205 |
| Streaming TTFT p50 / p95 / p99 | 757.566 / 1,511.044 / 1,578.020 ms (3 samples) |
| Total latency p50 / p95 / p99 | 466.627 / 1,265.984 / 1,531.804 ms (9 samples) |

The 9 successful requests consisted of 3 non-streaming, 3 streaming and 3 concurrent non-streaming calls. The error probe used a nonexistent model and correctly produced a classified error, not a fabricated success.

Real latency was broad: successful total latencies ranged from about 261 ms to 1,598 ms. The mock defaults should therefore be read as one plausible operating point, not an exact emulation. The Phase 3 real reference of roughly 630 ms for a normal completion and 433 ms TTFT is inside the observed range.

No real rate-limit response was induced. The real `429` latency distribution is therefore **not measured**, and the mock rate-limit timing is simulated.

## Simulated load experiments

The load scenarios use the mock service and calibrated delay. All rows in these scenarios have `source=stand-in`, and the summary file marks them `simulated: true`.

| Scenario | Requests | OK | Rate-limited | Timeouts | Errors | Retries | TTFT p50/p95/p99 ms | Total p50/p95/p99 ms | Queue p50/p95/p99 ms | Throughput |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| A-steady | 40 | 40 | 0 | 0 | 0 | 0 | 829.065 / 850.627 / 857.245 | 829.239 / 850.777 / 857.437 | 0 / 0 / 0 | 6.958 rps |
| B-burst | 30 | 30 | 0 | 0 | 0 | 0 | 817.115 / 842.938 / 845.627 | 1,643.186 / 3,244.761 / 3,246.141 | 812.5 / 2,406.0 / 2,428.01 | 9.224 rps |
| C-overload | 80 | 25 | 0 | 35 | 20 | 0 | 387.041 / 651.615 / 658.333 (25) | 307.889 / 633.399 / 654.101 (80) | 0 / 266.75 / 281.21 | 17.315 rps |
| D-per-minute-baseline | 40 | 30 | 10 | 0 | 0 | 0 | 828.106 / 849.435 / 854.930 (30) | 821.692 / 848.947 / 854.407 | 0 / 0 / 0 | 8.218 rps |
| D-per-minute-halved | 40 | 15 | 25 | 0 | 0 | 0 | 822.967 / 845.180 / 854.261 (15) | 1.480 / 840.005 / 850.344 | 0 / 0 / 0 | 8.207 rps |
| E-daily-budget | 25 | 10 | 15 | 0 | 0 | 0 | 206.678 / 225.683 / 227.055 (10) | 1.628 / 223.549 / 226.632 | 0 / 0 / 0 | 10.407 rps |

TTFT samples exist only for successful streaming requests. In C-overload and D-per-minute-halved, total-latency percentiles include fast rejection responses, so a low total p50 alongside a higher TTFT p50 is expected and is not a measurement error.

### Interpretation

- **A-steady:** 40 requests at 8 concurrent workers are served without queueing. Latency is close to the calibrated processing delay plus client overhead.
- **B-burst:** all 30 requests are admitted and succeed, but queue wait reaches about 2.4 s at p95 and total latency roughly doubles. The bounded queue absorbs the burst without failing requests.
- **C-overload:** the service is intentionally constrained to 2 concurrent requests with a 4-slot queue and 300 ms queue timeout. Only 25 of 80 requests succeed; 35 time out and 20 error. The higher apparent throughput comes from fast failures, not greater capacity.
- **D-per-minute-baseline:** a 30 requests/minute limit admits exactly 30 and rejects 10 within the run.
- **D-per-minute-halved:** halving the limit to 15 rejects 25 of 40, which demonstrates that the per-minute window is the controlling limit.
- **E-daily-budget:** a daily request budget of 10 admits 10 and rejects 15 with `daily_budget_exhausted`.

### Retry and budget experiments

| Scenario | Requests | OK | Rate-limited | Retries | Observation |
| --- | ---: | ---: | ---: | ---: | --- |
| retry-recovers | 1 | 1 | 0 | 1 | One transient failure recovered on the retry. |
| retry-worsens-no-retry | 6 | 3 | 3 | 0 | With no retry, 3 requests succeed and 3 are rejected for the exhausted minute. |
| retry-worsens-with-retry | 6 | 3 | 3 | 6 | Retrying every rejection adds 6 extra attempts but does not increase success; the minute remains exhausted. |
| daily-budget-no-retry | 5 | 3 | 2 | 0 | Daily budget exhaustion is classified as non-retryable, so it is not retried. |

These experiments show the intended policy: retry a transient failure once when it helps, do not retry a daily budget refusal, and do not create a retry storm against a per-minute limit.

## CSV and raw evidence

`results/results.csv` was written with the required column order:

```text
request_id,scenario,source,start_time,first_token_ms,total_ms,status,retries,tokens_in,tokens_out,retrieval_setting,answer_grade
```

- 283 data rows: 273 stand-in rows and 10 real calibration rows.
- Validated by reading the file back with the Phase 4 schema validator.
- `source` contains only `real` or `stand-in`.
- `status` contains only `ok`, `rate_limited`, `timeout` or `error`.
- `answer_grade` is empty for every row. No answer-quality grading was performed for Phase 4; an empty value means "not measured", not a passing grade.
- Raw per-request JSONL evidence is in `results/phase4/raw/`, including attempts, error codes, retry delays and queue wait.

The real rows use `scenario` values prefixed `real-` (`real-non_streaming`, `real-streaming`, `real-concurrent`, `real-error_probe`) and `source=real`. The stand-in rows never claim to be real.

## Automated tests and lint

```text
Phase 4 relay suite:   97 passed (includes 26 Phase 4 tests)
Default full suite:   185 passed, 5 skipped
Ruff check:           All checks passed
Ruff format --check:  35 files already formatted
Targets:              src/relay tests/relay scripts tests/rag/conftest.py
```

The 5 skips are the existing Phase 2 integration tests that require `--run-integration`. They were not enabled in this final run; the full offline suite still passes.

Phase 4 tests cover normal completion, streaming chunks, usage metadata, simulated markers, deterministic failure patterns, per-minute limits, daily request and token budgets, timeout responses, bounded-queue rejection and timeout, metrics, retry recovery, retry caps, retry-after limits, non-retryable budget errors, exception classification, load-row generation and CSV schema validation.

Evidence artifacts:

- `reports/phase4/pytest-phase4-final.xml`
- `reports/phase4/ruff-check.txt`

The offline test guard was extended in both `tests/relay/conftest.py` and `tests/rag/conftest.py` to permit numeric loopback sockets. This is required because asyncio creates a loopback socketpair on Windows when an event loop is constructed. External connections remain blocked, and no automated test contacts Groq.

## Phase 1-3 preservation

- The complete existing test suite still passes: `185 passed, 5 skipped`.
- No PDF, RAG index, evaluation question, Phase 1-3 report, or raw Phase 3 measurement was deleted or overwritten.
- The only Phase 1-3 test change is the loopback allowance in `tests/rag/conftest.py`; external network access remains prohibited.
- `.env` remains untracked. A direct check confirmed the Groq API key is absent from every Phase 4 report and result artifact.
- The mock service and all automated tests are offline; only the calibration script makes real Groq calls.

## Files created by this work

- `src/relay/mock/__init__.py`
- `src/relay/mock/__main__.py`
- `src/relay/mock/accounting.py`
- `src/relay/mock/config.py`
- `src/relay/mock/gate.py`
- `src/relay/mock/service.py`
- `src/relay/reliability.py`
- `src/relay/loadtest.py`
- `tests/relay/test_mock_service.py`
- `tests/relay/test_reliability.py`
- `tests/relay/test_loadtest.py`
- `scripts/calibrate_phase4.py`
- `scripts/run_phase4_experiments.py`
- `reports/phase4/completion-status.md`
- `reports/phase4/calibration/real-groq-calibration.json`
- `reports/phase4/load-test-summaries.json`
- `reports/phase4/pytest-phase4-final.xml`
- `reports/phase4/ruff-check.txt`
- `results/results.csv`
- `results/phase4/raw/A-steady.jsonl`
- `results/phase4/raw/B-burst.jsonl`
- `results/phase4/raw/C-overload.jsonl`
- `results/phase4/raw/D-per-minute-baseline.jsonl`
- `results/phase4/raw/D-per-minute-halved.jsonl`
- `results/phase4/raw/E-daily-budget.jsonl`
- `results/phase4/raw/retry-recovers.jsonl`
- `results/phase4/raw/retry-worsens-no-retry.jsonl`
- `results/phase4/raw/retry-worsens-with-retry.jsonl`
- `results/phase4/raw/daily-budget-no-retry.jsonl`

## Files modified by this work

- `pyproject.toml` - added `fastapi`, `httpx`, `uvicorn` dependencies and the `relay-mock` script entry.
- `tests/relay/conftest.py` - permits loopback event-loop sockets while blocking external services.
- `tests/rag/conftest.py` - same loopback allowance, required because the session-scoped guard otherwise overrides the relay guard in the full suite.

## Files deleted

None.

## Known limitations

- The load and retry results are simulations from a deterministic mock service. They are not measurements of Groq's real capacity, latency distribution or rate-limit behavior under load.
- Real calibration is a small shared free-tier sample: 9 successful requests. No real `429` was induced, so real rate-limit latency is unmeasured.
- The mock's token counts are a character-based heuristic, not a tokenizer. Token totals in stand-in rows are simulated usage metadata.
- TTFT is only defined for successful streaming requests. Percentile sample counts are reported explicitly; failed requests contribute to total latency and status counts, not TTFT.
- The overload scenario's throughput is inflated by fast failures and must not be read as useful capacity.
- `answer_grade` is empty because answer quality was not graded in Phase 4. Phase 3's evaluation questions were not re-scored.
- The retry experiments use small deterministic samples; they demonstrate policy behavior, not statistical success rates.
- The queue manager is in-process only. It is not a durable or distributed job queue.
- Integration tests requiring `--run-integration` were not run in the final Phase 4 verification.

## Commands to reproduce

```powershell
# Run the deterministic mock service
.venv\Scripts\python.exe -m relay.mock --scenario normal --host 127.0.0.1 --port 8099

# Real Groq calibration (makes real network requests; writes calibration JSON)
.venv\Scripts\python.exe scripts/calibrate_phase4.py

# Stand-in experiments (offline; merges stored real calibration rows by default)
.venv\Scripts\python.exe scripts/run_phase4_experiments.py

# Stand-in experiments only
.venv\Scripts\python.exe scripts/run_phase4_experiments.py --skip-real

# Tests and lint
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q tests/relay
.venv\Scripts\python.exe -m ruff check src/relay tests/relay scripts tests/rag/conftest.py
.venv\Scripts\python.exe -m ruff format --check src/relay tests/relay scripts tests/rag/conftest.py

# Validate the CSV schema and allowed values
.venv\Scripts\python.exe -c "from pathlib import Path; from relay.loadtest import read_results_csv; print(len(read_results_csv(Path('results/results.csv'))))"
```

## Phase 4 conclusion

Phase 4 is complete. The repository contains a working deterministic mock model service, a bounded reliability manager, real calibration evidence, simulated load and retry experiments, the required CSV and raw outputs, automated tests, lint verification, and this status report. No Phase 1-3 evidence was removed.
