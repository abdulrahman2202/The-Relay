# Phase 5.2 Remediation Report

Date: 2026-11-12
Scope: targeted reliability fixes for A2, A4, A8, A9, A10, A11 and A12.

Constraints honored: no full Groq evaluation was run, Phase 1-5 result artifacts were not
overwritten, no credentials or hidden model reasoning were captured, and failed turns still
expose empty `answer` and `claims` fields.

## Summary

Phase 5.2 adds diagnostic retention, conservative formatting-only quote matching, explicit
structured-output prompt guidance, and regression coverage for the seven answerable questions
that failed in Phase 5. The fixes address the two observed failure classes:

- A2, A8, A10, A11, A12: citation validation failures, with confirmed source-format hazards
  for each (dehyphenation, table pipes, superscript/fraction serialization, Unicode symbols).
  The exact generated quotations were not retained, so these are addressed as probable
  formatting mismatches rather than proven exact causes.
- A4, A9: stream-format failures after at least one claim had been emitted. The model later
  produced content that the strict parser rejected; the exact suffix was not retained.

Retrieval was not changed because gold evidence had already been retrieved for all seven
questions. The work does not claim that a future live Groq run is guaranteed to pass; it
removes the identified deterministic causes and makes any remaining failure diagnosable.

## Changes

### 1. Failure diagnostics

`src/relay/citations.py`

- Added `CitationValidationError`, carrying the rejected `quote` and `source_id`.
- Added `ClaimStream.failure`, populated once with:
  - the safe `RelayError` record;
  - the unparsed stream suffix;
  - the raw record when JSON parsing fails;
  - the candidate record when validation fails;
  - the last successfully parsed record;
  - the rejected quote and source ID;
  - already accepted claims and their count.
- `ClaimStream.finish()` now records incomplete records, missing completion markers, and
  terminator failures without discarding prior validated claims.

`src/relay/orchestrator.py`

- Added `TurnResult.failure_diagnostics`.
- The parser failure is copied into the turn result even while user-visible `answer` and
  `claims` are cleared.

`scripts/evaluate_final_answers.py`

- Persists diagnostics in each evaluation entry and each attempt record.
- Uses `PROMPT_VERSION` instead of a hardcoded prompt version.

### 2. Conservative citation canonicalization

`src/relay/citations.py`

- Replaced whitespace-only matching with `_canonical_positions`.
- Canonicalization covers documented formatting-only differences:
  - NFKC compatibility characters;
  - whitespace and table separator pipes;
  - superscript braces and caret markers;
  - line-break/dehyphenation differences such as `contextdependent` vs `context-dependent`;
  - slash-style split fractions such as `1\n√dk` vs `1/√dk`;
  - Unicode minus, multiplication, arrow and comparison symbols.
- Source offsets are retained after normalization so citation page/offset metadata still
  points at the original evidence.
- Matching remains lexical and order-preserving. Changed words, numbers, signs or units still
  fail. Numeric-support validation is unchanged and remains a separate check.

### 3. Prompt and stream contract

`src/relay/prompts.py`

- Bumped `PROMPT_VERSION` to `relay-phase3-v2`.
- The answer prompt now explicitly requires:
  - one complete JSON object per claim;
  - no prose, headings, equations or conflict explanations outside JSON;
  - separate structured claims for conflicting values;
  - one claim per part for multi-part questions;
  - exact evidence quoting, including table separators, superscripts, line breaks and Unicode;
  - `done` only after all claims or a refusal.
- Added illustrative format examples. They use synthetic values, not evaluation answers.

### 4. Regression tests

`tests/relay/test_citations.py`

- Canonical quote cases for A2 superscript minus, A8 dehyphenation, A10 table pipes,
  A11 multiplication symbol, A12 superscript/split fraction, A9 threshold notation and
  A4 table values.
- A negative test proving changed content is still rejected.
- Structured conflicting claims for A4 values `41.8` and `41.0`.
- Multiple structured claims for the A9 threshold and initial-probability answer.
- Diagnostics tests for rejected quotes and unparsed stream suffixes.

`tests/relay/test_orchestrator.py`

- Citation-validation failure retains diagnostics while `answer` and `claims` remain empty.
- Stream-format failure retains the last valid claim and unparsed suffix while the user-visible
  answer remains empty.
- Successful turns have no failure diagnostics.

## Failure Coverage

| ID | Phase 5 failure | Remediation | Deterministic coverage |
| --- | --- | --- | --- |
| A2 | Citation quote mismatch | Superscript/caret and Unicode-minus canonicalization; exact quoting instruction | Superscript canonical quote case |
| A4 | `stream_format` after partial output | Structured conflict claims; strict stream framing; diagnostics | Two conflicting structured claims for 41.8/41.0 |
| A8 | Citation quote mismatch | Dehyphenation canonicalization | `contextdependent` vs `context-dependent` |
| A9 | `stream_format` after partial output | Multi-part structured claims; diagnostics | Threshold and initial-probability claims |
| A10 | Citation quote mismatch | Table-pipe canonicalization | Table row with pipes vs spaces |
| A11 | Citation quote mismatch | Unicode multiplication canonicalization | `3.6x` vs `3.6×` |
| A12 | Citation quote mismatch | Superscript, brace and split-fraction normalization | `^{√}dk` and `1\n√dk` vs `1/√dk` |

## Verification

Commands run:

```text
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

Observed results:

```text
203 passed, 5 skipped in 105.79s
All checks passed!
68 files already formatted
```

The five skipped tests are the existing integration tests that require
`--run-integration`; they were not run against the live model.

## Limitations

- No live Groq answer-quality evaluation was run in Phase 5.2. The regression tests reproduce
  the identified formatting and stream-framing conditions synthetically.
- The exact original model-generated quotations for A2/A8/A10/A11/A12 and the exact A4/A9
  malformed suffixes were unavailable. Future runs will now retain diagnostics that make
  such failures inspectable.
- Canonicalization intentionally remains lexical. It does not perform semantic entailment,
  fuzzy matching, or paraphrase acceptance.
- Prompt examples are illustrative and do not encode evaluation gold answers.
- A successful live re-evaluation still depends on the model following the stronger prompt;
  that remains to be confirmed in an approved Groq run.
