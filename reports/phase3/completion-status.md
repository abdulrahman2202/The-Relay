# Phase 3 Completion Status

- Repository: `C:\Programming\The-Relay`
- Date: 2026-11-11
- Model: `openai/gpt-oss-20b`
- Prompt version: `relay-phase3-v1`
- Scope: Phase 3 only. Phase 4, the mock model service, queue manager, and load testing were not started.

## Status summary

| Requirement | Status | Evidence |
| --- | --- | --- |
| A. Groq LLM service | COMPLETE | Mocked tests plus real normal and streaming requests |
| B. Orchestration pipeline | COMPLETE | Real 6-stage answerable run with retrieval, generation, refusal branch and validation |
| C. Actual Groq tool calling | COMPLETE | Real `finish_reason="tool_calls"`, parsed arguments, local RAG execution |
| D. Evidence-grounded generation | COMPLETE | JSONL claim protocol, quote validation, number checks, refusal paths, prompt-injection separation |
| E. Streaming and metrics | COMPLETE | Incremental output, first-token, retrieval, planning, generation and validation timings |
| F. Terminal interface | COMPLETE | `python -m relay`, multiple-question loop, `exit`, errors, sources and metrics |
| G. Evaluation questions | COMPLETE | 20 self-written questions: 12 answerable, 8 unanswerable |

Nothing in the table is marked COMPLETE only because source code exists. Every item has a passing automated test and/or a real Groq verification record in `reports/phase3/implementation-2026-11-11/real-groq-verification.json`.

## What already existed

The previous agent had already created the `src/relay` package, `tests/relay`, the Phase 3 test-path configuration in `pyproject.toml`, and an initial baseline report. The existing implementation covered:

- Config loading from `.env` without exposing the API key.
- A synchronous Groq adapter with completion, streaming, usage extraction, timing, timeouts and sanitized errors.
- A bounded orchestration flow that classifies the question, requests a required tool call, executes the local RAG adapter, selects evidence, streams JSONL claims, validates citations and refuses empty/insufficient evidence.
- A terminal loop in `relay.cli`.
- Mocked tests for the LLM, tools, citations, orchestrator, retrieval adapter and terminal.

The initial relay test run in the preserved baseline had 65 passed tests.

## Defects found and fixed during real verification

Real Groq calls exposed two defects that the mocked tests did not catch.

1. **Adjacent JSON objects without newlines.** GPT-OSS emitted a claim object immediately followed by the `{"type":"done"}` object on the same line. The original line-based `ClaimStream` rejected this as `invalid_json`. I replaced newline splitting with an incremental parser that consumes complete JSON objects while respecting strings, escapes and nested braces/arrays.
2. **Omitted tool arguments.** GPT-OSS sometimes omitted the optional `preset` field in a tool call. Groq's server-side schema validation then returned HTTP 400 `tool_use_failed` before the application could recover. The tool schema now requires only `query`; omitted `strategy`/`preset` values default to the configured retrieval settings, and supplied values are still validated strictly.

A third real attempt failed closed rather than fabricating an answer: for the question about Transformer attention heads, GPT-OSS returned the placeholder quote `"... 16 ..."`. Citation validation correctly rejected it. No unsupported answer was displayed. This is recorded as a known limitation below, not as a success.

## Files created by this work

- `reports/phase3/completion-status.md`
- `reports/phase3/evaluation/questions.json`
- `reports/phase3/implementation-2026-11-11/real-groq-verification.json`
- `reports/phase3/implementation-2026-11-11/pytest-phase3-final.xml`
- `reports/phase3/implementation-2026-11-11/pytest-phase3-integration.xml`
- `reports/phase3/implementation-2026-11-11/ruff-check.txt`
- `scripts/verify_phase3.py`

## Files modified by this work

- `src/relay/citations.py` - robust incremental JSON-object stream parser.
- `src/relay/tools.py` - schema defaults for omitted optional tool arguments.
- `tests/relay/test_citations.py` - adjacent-object, embedded-brace/escaped-quote and incomplete-record tests.
- `tests/relay/test_tools.py` - omitted optional argument/default tests.

## Files preserved from the previous agent

- `src/relay/*` (all other modules), `tests/relay/*` (all other tests), `pyproject.toml`, `reports/phase3/implementation-2026-11-11/baseline.json`, and `reports/phase3/implementation-2026-11-11/pytest-relay-initial.xml`.

## Files deleted

None.

## Automated test results

All automated Phase 3 tests are offline. `tests/relay/conftest.py` blocks socket connections, so no automated test can contact Groq.

```text
Default full suite:        159 passed, 5 skipped
Phase 3 relay suite:       71 passed
Integration full suite:    164 passed, 0 skipped (442.99 s)
                          (pytest --run-integration, cached local MiniLM)
```

The default five skips are the existing Phase 2 integration tests that require `--run-integration`. Running them explicitly exercises real local MiniLM inference against all three PDFs and still passes, which demonstrates Phase 2 compatibility.

JUnit evidence:

- `reports/phase3/implementation-2026-11-11/pytest-phase3-final.xml`
- `reports/phase3/implementation-2026-11-11/pytest-phase3-integration.xml`

Covered behaviours include normal completion, streaming, API errors, rate limits, timeouts, tool-call parsing, maximum tool calls, empty retrieval, retrieval exceptions, supported questions, unsupported questions, citation validation, invalid arguments, stream interruption and terminal loops.

## Ruff results

```text
ruff check:          All checks passed
ruff format --check: 20 files already formatted
Targets: src/relay tests/relay scripts/verify_phase3.py
```

Recorded in `reports/phase3/implementation-2026-11-11/ruff-check.txt`.

## Real Groq API verification

These are real network requests, not mocked tests. The safe evidence file contains no API key, and the key was checked to be absent from all Phase 3 artifacts.

| Check | Result | Real usage / timing |
| --- | --- | --- |
| Normal completion | `RELAY OK`, `finish_reason=stop` | 84 input, 21 output, 0.630 s |
| Streaming completion | `1 2 3 4 5`, `finish_reason=stop` | 86 input, 32 output, 0.444 s, first token 0.433 s |
| Real tool call | `finish_reason=tool_calls`, one `search_research_papers` call | 448 input, 43 output, 0.487 s |
| Answerable question | `answered` with validated citations | 3,424 input, 238 output, 1.137 s warm process |
| Unsupported constraint question | `refused`, no generation request | 456 input, 50 output, 0.794 s |
| Model-driven refusal | `refused` after a real generation stream | 3,363 input, 68 output, 0.873 s |

### Tool-calling verification

Real model output for the answerable question contained a structured function call with model-generated arguments:

```json
{"query": "Moshi latency theoretical practical", "strategy": "bm25", "preset": 600}
```

The adapter parsed and validated those arguments, executed the existing `RetrievalPipeline`, and received four Moshi passages from the local Chroma index. The returned passages included paper title, arXiv identifier and version, physical page numbers and source identifiers. No tool call was simulated from ordinary text; a dedicated test proves ordinary text cannot bypass the required tool-call interface.

The first retrieval in a fresh process took 10.616 s; warm retrieval in the same process took 0.095 s. The CLI starts a fresh process per `--question`, so its first-query metric shows the cold value.

### Streaming verification

- Real stream delivered content incrementally before `finish_reason=stop`.
- First generated content token was observed at 0.433 s in the standalone stream check.
- A partial or interrupted stream is never marked successful: tests cover a missing terminator, a transport failure after partial content and a `KeyboardInterrupt` during streaming.
- Usage is recorded only when Groq actually supplies it; an interrupted stream leaves unknown usage as unknown.
- Citation validation occurs on complete claim objects before their text reaches the terminal.

## Example terminal interaction

Real command:

```powershell
.venv\Scripts\python.exe -m relay --question "What are Moshi's theoretical and practical latency?"
```

Real output excerpt:

```text
Assistant:
Moshi’s theoretical latency is 160 ms and its practical latency is 200 ms. [S2]

Sources:
- [S2] Moshi: a speech-text foundation model for real-time dialogue (arXiv:2410.00037v1, p. 1)
  https://arxiv.org/pdf/2410.00037v1#page=1

Status: answered
Metrics:
- Time to first answer token: 12.163 s
- Generation stream first token: 0.657 s
- Total response time: 12.164 s
- Retrieval: 10.760 s
- Evidence selection: 0.026 s
- LLM planning: 0.623 s
- LLM generation: 0.755 s
- Citation validation: 0.001 s
- Input tokens: 3386
- Output tokens: 183
```

Second real answerable question (`Adam optimizer`):

```text
The Transformer uses the Adam optimizer with β1 = 0.9 and β2 = 0.98. [S4]
- [S4] Attention Is All You Need (arXiv:1706.03762v7, p. 7)
Status: answered
Input tokens: 2674; Output tokens: 158; Total time: 11.607 s
```

Real unsupported question:

```text
.venv\Scripts\python.exe -m relay --question "What p95 latency does Moshi measure on iPhone 15 Pro running iOS?"
```

```text
The supplied papers do not provide enough evidence to answer that question.
Status: refused
Missing constraints: p95, iPhone 15 Pro, iOS
```

Interactive smoke test with piped input (`hi`, then `exit`) started `python -m relay`, answered the help branch without a network call, and exited with `Goodbye.`

## Citation-validation results

The JSONL claim protocol requires one to six claims, each with one to three evidence items. Each citation is checked against the retrieved passage for:

- A source identifier that exists in the retrieved evidence.
- A verbatim quotation (whitespace-normalized) of 12-1,200 characters.
- Page attribution and source URL derived from the source passage, not the model.
- Numeric consistency: every number in the claim must occur in its supporting quotations.

Real answerable result: one claim, two citations, zero validation errors. Invalid source IDs, fabricated quotes, unsupported numbers, control characters, free-form citations and missing completion markers are rejected by tests.

This validation prevents the specific failure mode where the model invents a quote, but it is **not** a semantic entailment checker. A quote can be real and still fail to justify the full claim. Prompt instructions alone are not claimed to guarantee factual correctness.

## Manual PDF citation checks

The cited pages were independently opened from the original PDFs with PyMuPDF, not re-read from Chroma chunk text.

- Moshi p. 1: quote about the real-time full-duplex model with 160 ms theoretical and 200 ms practical latency - found.
- Moshi p. 26: quote about settling on 160 ms theoretical latency with acoustic delays of 2 then 1 - found.
- Attention p. 7: independent check found the Adam optimizer text with `β1 = 0.9`, `β2 = 0.98` - found.

The automated `citation_pdf_checks` entries for the Moshi citations both report `ok: true` in `real-groq-verification.json`.

## Phase 1 and Phase 2 preservation

- No Phase 1 or Phase 2 source, test, PDF, documentation, audit report or evaluation data was modified or deleted.
- The existing RAG integration suite passes with the real cached MiniLM model.
- The Chroma collections still contain the same six collection names and counts: 181, 243, 450, 443, 173 and 251 records.
- Thirteen protected files under `data/chroma-v2/` changed hash when Chroma opened the store during real retrieval (internal SQLite/segment persistence files). The collection contents and retrieval behaviour are unchanged; no re-ingestion was performed.
- `.env` remains untracked and was never printed or copied into a report. A direct check confirmed the API key is absent from Phase 3 artifacts.

## Known limitations

- Citation validation checks quote presence and numeric consistency; it does not prove semantic entailment.
- GPT-OSS can occasionally produce placeholder quotations or omit an optional tool argument. Omitted optional arguments are defaulted safely; invalid quotations cause a fail-closed error rather than a fabricated answer. The observed attention-head question failed citation validation instead of answering.
- The evidence assessment is a conservative literal-constraint check, not a full natural-language entailment model.
- A fresh process has a cold retrieval cost of roughly 10.6 s; warm retrieval is roughly 0.1 s. No performance optimization was attempted.
- The 20-question evaluation set exists, but a full scored answer-quality evaluation is future work. No answer-quality scores are claimed here.
- The model may emit adjacent JSON objects despite the JSON Lines instruction; the parser now tolerates this, but the prompt is not followed perfectly.

## Commands to run

```powershell
.venv\Scripts\python.exe -m relay
.venv\Scripts\python.exe -m relay --question "What are Moshi's theoretical and practical latency?"
.venv\Scripts\python.exe -m relay --question "What is the practical latency of Moshi?" --json
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q --run-integration
.venv\Scripts\python.exe -m ruff check src/relay tests/relay scripts/verify_phase3.py
.venv\Scripts\python.exe -m ruff format --check src/relay tests/relay scripts/verify_phase3.py
.venv\Scripts\python.exe scripts/verify_phase3.py
```

The last command makes real Groq requests and writes `reports/phase3/implementation-2026-11-11/real-groq-verification.json`.

## Remaining assignment requirements and recommended next phase

- Run the 20-question Phase 3 evaluation set and score answer quality separately; do not infer scores from this implementation report.
- Then proceed to the assignment's next phase: the mock model service, queue manager and load testing. These were explicitly out of scope here and were not implemented.
