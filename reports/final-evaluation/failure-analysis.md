# Phase 5.1 Failure Analysis

**Status:** root-cause analysis complete; no remediation implemented  
**Analysis date:** 2026-11-12  
**Scope:** seven failed answerable questions from the Phase 5 run: `A2`, `A8`, `A10`, `A11`, `A12` (`citation_validation`) and `A4`, `A9` (`stream_format`)  
**Basis:** saved Phase 5 artifacts, production code inspection, and offline reproduction only. No Groq requests were rerun, no application code was changed, and no existing evaluation artifact was modified.

## Executive summary

The seven failures are not one defect and are not a retrieval failure.

- All seven questions had the annotated gold evidence in the production BM25 top-4 context. Four had complete gold coverage at BM25 rank 1; `A4`, `A9`, and `A10` had complete coverage at rank 2.
- The five `citation_validation` failures are exact-substring rejections. The saved error is `The supporting quotation is absent from the cited passage.` The numeric-support check was not reached. The model either paraphrased, normalized, or quoted across a source-format boundary that the validator does not normalize away.
- The two `stream_format` failures occurred after at least one valid claim had already been displayed (`A4`: 114 characters, `A9`: 94 characters). The parser then encountered a non-`{` character where the next structured record was required. The first claim was valid; the stream framing broke afterward.
- The exact model quotations and exact malformed stream tails were not saved. `TurnResult` clears `answer` and `claims` on failure, and neither the raw evaluator artifact nor `ClaimStream` retains the failed stream buffer. This is a material observability gap and prevents definitive attribution of each citation failure to a specific generated string.
- The source text is valid Unicode, not mojibake. Earlier console output showed replacement characters because of PowerShell display encoding. Python UTF-8 reads confirm clean `β`, `ε`, `−`, `√`, `×`, and `→` characters in the stored source text.
- The strict citation validator is not generally broken: five other answerable questions produced valid, validated citations. The failures expose a mismatch between exact source representation, the model's quoting behavior, and an unobservable failure path.

No single fix should be applied to all seven. The highest-value first step is to preserve failure context so a future run can identify the exact rejected quote and malformed stream suffix. That diagnostic change must not weaken validation.

## Evidence base

Primary artifacts:

- `reports/final-evaluation/raw/answer-quality-raw.json`: final result, sources, stages, metrics, and one final attempt per failed question.
- `reports/final-evaluation/answer-quality-results.json`: aggregate results and A4 conflict metadata.
- `reports/final-evaluation/manual-grading.csv`: blank final grades; failed answers have blank answer/citation fields.
- `reports/final-evaluation/raw/retrieval-rankings.json`: BM25/vector/hybrid top-50 rankings and gold-span coverage.
- `reports/rag/audit-2026-11-11/questions.json`: annotated evidence units and expected answers.
- `reports/rag/audit-2026-11-11/resolved-evidence.json`: resolved evidence spans.

Production code:

- `src/relay/prompts.py`: JSON Lines contract and exact-quote instruction.
- `src/relay/citations.py`: quote validation, numeric support, and structured stream parser.
- `src/relay/orchestrator.py`: streaming, display counting, failure handling, and result clearing.
- `src/retrieval/extraction.py`: extraction-time text transformation.
- `src/retrieval/text.py`: line-break dehyphenation.
- `src/retrieval/layout.py`: NFKC/whitespace normalization and superscript serialization.
- `scripts/evaluate_final_answers.py`: raw artifact writer.

Run conditions: `openai/gpt-oss-20b`, prompt `relay-phase3-v1`, BM25, preset `600`, evidence budget `3000`, `temperature=0`, `seed=0`.

## Observed failure set

| ID | Error | Saved message | Displayed characters | Retained claims | BM25 gold coverage |
|---|---|---|---:|---:|---|
| A2 | `citation_validation` | The supporting quotation is absent from the cited passage. | 0 | 0 | Complete, rank 1 |
| A8 | `citation_validation` | The supporting quotation is absent from the cited passage. | 0 | 0 | Complete, rank 1 |
| A10 | `citation_validation` | The supporting quotation is absent from the cited passage. | 0 | 0 | Complete, rank 2 |
| A11 | `citation_validation` | The supporting quotation is absent from the cited passage. | 0 | 0 | Complete, rank 1 |
| A12 | `citation_validation` | The supporting quotation is absent from the cited passage. | 0 | 0 | Complete, rank 1 |
| A4 | `stream_format` | Expected a structured answer object. | 114 | 0 | Complete, rank 2 |
| A9 | `stream_format` | Expected a structured answer object. | 94 | 0 | Complete, rank 2 |

`Retained claims` is zero for every failure because the orchestrator explicitly clears the result on failure:

```python
# src/relay/orchestrator.py:257-258
if result.status in {"failed", "cancelled"}:
    result.answer, result.claims = "", []
```

`displayed_characters` is incremented before that clearing (`src/relay/orchestrator.py:161`), which is why `A4` and `A9` still show partial output.

## What did not cause the failures

### Retrieval did not miss the evidence

Every failed question had gold evidence in the BM25 top-4 context:

- `A2`: gold Adam hyperparameters and warmup evidence at rank 1, both units covered.
- `A4`: both table/prose conflict units covered at rank 2.
- `A8`: the single gold unit covered at rank 1.
- `A9`: both threshold/initial-probability units covered at rank 2.
- `A10`: all three Table 4 units covered at rank 2.
- `A11`: the Figure 6 unit covered at rank 1.
- `A12`: both gold units covered at rank 1.

The evidence gate also classified each as `candidate_evidence`, and each tool call returned four evidence chunks. This was a generation, quoting, or framing failure, not an empty-retrieval or missing-evidence failure.

### The failures are not rate limits, timeouts, or tool errors

Each failed question has one final attempt record with a non-retryable application error. No final attempt records `rate_limit`, `timeout`, `interrupted`, or a tool failure. Initial rate-limited attempts described in the evaluation summary are not the cause of these final statuses.

### The citation failures are not numeric-support failures

`validate_claim` checks the quote first and only then checks numeric support:

- Quote membership check: `src/relay/citations.py:108-112`.
- Numeric support check: `src/relay/citations.py:128-131`.

All five citation failures report the quote-absent message, not `A claimed number is absent from its supporting quotations.` The first failing quote was not found after whitespace collapsing. Numeric support was never evaluated for that claim.

### The stream failures are not truncated cited output

`A4` and `A9` did not fail with `incomplete_stream`, `incomplete_answer`, or `Unbalanced structured answer output.` They failed with the first-character check in `_object_end`:

```python
# src/relay/citations.py:135-142
def _object_end(text: str) -> int | None:
    if not text or text[0] != "{":
        raise RelayError("stream_format", "Expected a structured answer object.")
```

This means at least one complete object had already been consumed and validated, and the next non-whitespace character was not `{`. The error is specifically a framing violation, not an invalid JSON object, an invalid record type, or an unclosed object.

### Extraction mojibake is not supported by the current artifacts

Raw JSON loaded as UTF-8 contains clean Unicode source text, including:

- `A2`: `β1 = 0.9`, `β2 = 0.98`, `ε = 10^{−9}`.
- `A10`: `59.9 → 66.3`.
- `A11`: `3.6x` in the figure label and `3.6×` in the caption.
- `A12`: `^{√}dk` and `√dk`.
- `A9`: `bt = 1{pt ≥0.5}` and `p1 = 1.0`.

The apparent replacement-character glyphs in earlier PowerShell output were a console encoding artifact. No U+FFFD replacement characters or corrupted math were found in the stored source strings.

## Citation-validation failures

### Mechanism

The answer prompt requires a verbatim quote:

> Quotes must be 12-1200 characters, verbatim except whitespace, and support the WHOLE claim.

(`src/relay/prompts.py:32-33`)

The validator normalizes only whitespace before searching:

```python
# src/relay/citations.py:17-25
def _normalized_positions(text: str) -> tuple[str, list[int]]:
    characters, positions = [], []
    for match in re.finditer(r"\S+", text):
        if characters:
            characters.append(" ")
            positions.append(match.start())
        characters.extend(match.group())
        positions.extend(range(match.start(), match.end()))
    return "".join(characters), positions
```

```python
# src/relay/citations.py:108-113
needle = " ".join(quote.split())
start = normalized.find(needle)
if start < 0:
    raise RelayError(
        "citation_validation", "The supporting quotation is absent from the cited passage."
    )
```

The production evidence text is not the raw PDF text. It has already passed through extraction transformations:

- `dehyphenate` removes line-break hyphenation during extraction (`src/retrieval/extraction.py:104`, using `src/retrieval/text.py:14-16`).
- `layout.normalize` applies NFKC normalization and whitespace collapsing (`src/retrieval/layout.py:35-37`).
- `_span_text` serializes superscripts as `^{...}` (`src/retrieval/layout.py:40-50`).
- Table rows are flattened with explicit ` | ` cell separators.

Those transformations are useful for retrieval, but they make some natural, semantically correct quotes fail the exact-substring check.

### Confirmed source hazards

The following behavior was verified with the same normalization function used by `validate_claim`. These are confirmed ways a quote can fail; they are not proof of the exact text the model generated.

| ID | Production source form | A natural quote that fails | What still passes |
|---|---|---|---|
| A2 | `ε = 10^{−9}` | `ε = 10−9`, `ε = 10^-9`, `ε = 10^{-9}` | `ε = 10^{−9}` exactly |
| A8 | S1: `contextdependent`; S4: `context- dependent` | `context-dependent` against S1 or S4 | S3's `context-dependent`, or S4's `context- dependent` exactly |
| A10 | `Transformer \| 3.62 \| T15 \| 0.7404 \| 0.599` | `Transformer 3.62 T15 0.7404 0.599`; `59.9% to 66.3%` | Row with pipes, or `59.9 → 66.3` exactly |
| A11 | `3.6x more data efficient than isotropic model` | `3.6 times more data efficient than isotropic models` | The exact figure label, or the exact caption `approximately 3.6× less data` |
| A12 | `divide each by ^{√}dk`; fraction split as `1` newline `√dk` | `1/√dk`; `divide each by √dk` | `divide each by ^{√}dk`; `1` whitespace `√dk` |

Notes on the mechanisms:

- **Hyphenation/dehyphenation (A8, also A11 and A4 source text).** `dehyphenate` joins an alphabetic line-break hyphen: `context-\ndependent` becomes `contextdependent`, and `pre-\ndecay` becomes `predecay`. Natural quotes restore the hyphen. `A8` also has a source with a space after the hyphen (`context- dependent`), so normalizing that space away causes rejection.
- **Table serialization (A4, A10).** Table rows are exposed as pipe-separated strings. A model that quotes the row as prose, or omits the separators, is not quoting a contiguous source substring.
- **Mathematical layout (A2, A12).** Superscripts are encoded as `^{...}` and fractions can be split across lines. Natural notation such as `10^-9` or `1/√dk` does not match the stored form. The validator's NFKC normalization does not remove `^{}` or convert a split fraction into a slash form.
- **Unicode typography (A11, A10).** The source distinguishes `3.6x` from `3.6×`, and uses a Unicode arrow `→`. The validator does not normalize those choices. `_numbers` normalizes U+2212 for numeric support, but that happens only after the quote itself matches.

### Per-question assessment

#### A2 — Adam optimizer, beta values, epsilon, and warmup steps

Evidence is present and complete in S1, page 7. The exact source line is:

```text
We used the Adam optimizer [20] with β1 = 0.9, β2 = 0.98 and ε = 10^{−9}.
...
warmup_steps = 4000.
```

The main hazard is the superscript representation and the Unicode minus in `10^{−9}`. The audit's expected quote uses `ε = 10−9` without the `^{}` markup, which is not a literal substring of the production chunk. If the model quoted `10^-9`, `10−9`, or `10^{-9}`, the quote would be rejected even though the values are correct. The model could have passed with `warmup_steps = 4000` or the exact line.

**Assessment:** probable formatting/normalization mismatch; exact generated quote unknown. The source hazard is confirmed; the specific model output is not.

#### A8 — H-Net dynamic chunking and tokenization

Evidence is present at BM25 rank 1. The clearest hazard is the dehyphenated S1 text:

```text
... learn content- and contextdependent discrete segmentation strategies ...
```

Natural wording would be `context-dependent`; S1 has no hyphen, and S4 has `context- dependent` with a space. S3 does contain `context-dependent`, so an exact quote from S3 would pass. The failure means the model did not produce a quote that matched the exact form of the source it cited.

**Assessment:** high-confidence source-format hazard, specifically dehyphenation or hyphen spacing; exact model quote unknown.

#### A10 — Table 4 XWinograd-zh accuracies

The relevant source is a pipe-serialized table:

```text
Transformer | 3.62 | T15 | 0.7404 | 0.599 | 3.58 | T13 | 0.3376
...
H-Net (2-stage) | 5.81 | T30 | 0.7032 | 0.663 | 7.23 | T28 | 0.3161
```

The prose alternative is `59.9 → 66.3 on XWinograd-zh`. Natural answers usually render table rows without pipes, or convert `0.599`/`0.663` to `59.9%`/`66.3%`, or write `to` instead of `→`. All of those fail the exact-substring check. The audit's gold quotes use newline-separated cells rather than the production pipe format, so they are also not a literal validator oracle.

**Assessment:** probable table-serialization or percentage/arrow normalization mismatch; exact generated quote unknown.

#### A11 — Figure 6 data efficiency

The source contains multiple near-equivalent forms:

- Figure label: `3.6x more data efficient than isotropic model`
- Caption: `approximately 3.6× less data`
- Appendix: `3.6× the data efficiency of an isotropic architecture`

A natural answer such as `3.6 times more data efficient than isotropic models` changes `x` to `times`, singular to plural, and wording. It is not a contiguous source substring. The question wording (“what data-efficiency improvement”) invites exactly this kind of paraphrase. An exact caption or figure-label quote would pass.

**Assessment:** high-confidence paraphrase/typography hazard; exact generated quote unknown.

#### A12 — Scaled dot-product attention

The source preserves the paper's mathematical layout:

```text
divide each by ^{√}dk
...
To counteract this effect, we scale the dot products by
1
√dk .
```

The audit's expected quote `divide each by √dk` is not a literal substring because the production text has `^{√}dk`. A model that writes `1/√dk` (the standard notation) is also not quoting the source, because the source has a line-broken fraction with no slash. A model that copies `divide each by ^{√}dk` or the exact split fraction would pass.

**Assessment:** high-confidence mathematical-layout mismatch; exact generated quote unknown.

### What the citation failures prove

Confirmed:

- The first failing quote was absent after whitespace normalization.
- The cited source existed and the quote length/structure constraints were satisfied.
- The numeric-support check was not reached.
- The source contains formatting hazards that make natural equivalent quotes fail.

Not confirmed:

- The exact text the model generated for each quote.
- Whether the model paraphrased, used a different notation, combined text across a boundary, or cited a different but present source form.
- Whether the model would have passed with a different citation choice from the same retrieved context.

The distinction matters: a valid fix must not assume all five failures are the same kind of quoting error.

## Stream-format failures

### Mechanism

`ClaimStream` validates and emits complete JSON objects. After each object, `_consume` strips whitespace and calls `_object_end` on the remainder:

```python
# src/relay/citations.py:185-196
def _consume(self) -> None:
    while True:
        self.buffer = self.buffer.lstrip()
        if not self.buffer:
            return
        end = _object_end(self.buffer)
        if end is None:
            return
        raw, self.buffer = self.buffer[:end], self.buffer[end:]
        self._value(strict_json(raw))
```

`_object_end` raises `Expected a structured answer object.` when the first remaining character is not `{`.

For `A4` and `A9`:

1. At least one claim object was complete, validated, and emitted.
2. `displayed_characters` became positive (`114` for A4, `94` for A9).
3. The next non-whitespace content did not start a JSON object.
4. The parser raised `stream_format`.
5. The orchestrator cleared `answer` and `claims`, leaving only the error and display count.

This is confirmed by the error message itself. The following related errors did not occur and would indicate different problems:

- `Expected a structured answer record.` — the next object parsed but was not a dictionary.
- `Unexpected, mixed or excessive answer records.` — a parsed record had the wrong type or exceeded limits.
- `Unbalanced structured answer output.` — an object closed incorrectly.
- `The answer ended with an incomplete record.` — the stream ended mid-object.
- `The answer did not include its completion marker.` — framing was otherwise valid but `done` was absent.

### A4 — BLEU table and known source conflict

`A4` asks for Table 2 BLEU values. The production source contains both the table row and the prose conflict:

- Table 2 page 8: `Transformer (big) | 28.4 | 41.8`.
- Prose page 8: `our big model achieves a BLEU score of 41.0...`.

The system prompt says:

> Expose source conflicts rather than silently resolving them.

(`src/relay/prompts.py:17`)

The output contract, however, only defines `claim`, `refusal`, and `done` records and says there must be no extra prose. A plausible failure sequence is:

1. The model emits one valid table claim, which is displayed (114 characters).
2. It then tries to explain the `41.8` versus `41.0` conflict as prose after the claim.
3. The parser sees the first prose character instead of `{` and raises `stream_format`.

This is a strong contextual hypothesis because A4 is the only failed question with a known source conflict and the prompt explicitly requires exposing it. The exact tail is not saved, so this is not proven. The failure could also be a Markdown fence, a bare explanation, or another non-JSON continuation.

The conflict itself is verified and must remain visible in any remediation:

- Table 2, physical page 8: EN-DE `28.4`, EN-FR `41.8`.
- Prose, physical page 8: EN-FR `41.0`.
- No third value should be invented, and the two values must not be silently collapsed.

### A9 — Threshold and first-position probability

`A9` has two required facts:

- `bt = 1{pt ≥0.5}` on page 6.
- `p1 = 1.0 by definition, ensuring the sequence begins with a boundary` on page 6.

The first claim was displayed (94 characters), so at least one fact was already structured and validated. The subsequent content was not a JSON object. A plausible sequence is that the model emitted the threshold claim and then wrote the second fact as prose, a Markdown bullet, or an equation without wrapping it in a second claim object. The exact suffix is not saved.

Unlike the citation failures, this is not evidence that the first claim's citation was invalid. The first claim passed validation. The failure is purely a protocol/framing violation after that claim.

### What the stream failures prove

Confirmed:

- At least one claim was validated and shown before failure.
- The next non-whitespace content was not a JSON object start.
- The error is application-side framing validation, not a provider rate limit, timeout, or authentication error.
- The result-clearing path discarded the claims that had already been validated.

Not confirmed:

- The exact text after the first claim.
- Whether the remainder contained a second valid claim with invalid formatting, a prose conflict explanation, a Markdown fence, or an equation.
- Whether the model would have completed the protocol if the parser had not aborted the request.

## Root-cause synthesis

| Layer | Finding | Confidence | Contribution |
|---|---|---|---|
| Evidence representation | Extraction introduces `^{...}`, pipe-separated tables, and dehyphenated words; quote matching only normalizes whitespace. | Confirmed | Creates the conditions for all five citation rejections. |
| Model quoting | The model did not reproduce an exact contiguous substring for the cited source. | Confirmed by the rejection; exact text unknown | Direct cause of the five citation failures. |
| Output protocol | The model emitted non-JSON content after a valid claim in A4/A9. | Confirmed for framing; exact content unknown | Direct cause of both stream failures. |
| Prompt tension | “Expose source conflicts” has no structured note field and can encourage prose after a claim. | Probable for A4, not proven | Likely contributor to A4. |
| Multi-part answer handling | A9 asks two facts; the model may have handled the second outside the claim stream. | Probable, not proven | Likely contributor to A9. |
| Observability | Failed answers are cleared and the raw stream buffer is not persisted. | Confirmed | Prevents definitive per-question RCA. |
| Retry policy | Validation and stream-format errors are non-retryable; each failed question has one final attempt. | Confirmed behavior | Turns a single formatting/quoting miss into a final failure. |
| Evaluation annotations | Some audit “quotes” are normalized and are not literal substrings of production text (for example A2's `10−9`, A10's newline table rows, A11's `pre-\ndecay`). | Confirmed | Evaluation-quality issue; does not directly cause the Groq failure because the model never sees the audit quote. |
| Extraction corruption | No U+FFFD or corrupted math was found in the stored source. | Refuted | Not a cause. |

There is no evidence for a single systemic bug in `validate_claim`. The strict quote policy is doing what it was written to do. The system problem is that the production evidence representation and the model's natural rendering are not aligned, and the failure path destroys the evidence needed to tell exactly which mismatch occurred.

## Validator and safety assessment

The strict quote validator should not be weakened as a shortcut.

- It rejects fabricated quotes, paraphrases, and citations to non-retrieved sources.
- It prevents a claim from being displayed before its support is checked.
- It correctly passed the five successful answerable questions; those claims contain exact contiguous quotes, including quotes with line breaks and Unicode text.
- The five failures are exact-substring rejections, not evidence that the validator accepted unsupported content.
- The `A4` and `A9` failures are downstream framing errors, not validator false positives.

There is a legitimate distinction between:

1. **Strictness by design:** rejecting a semantically similar but non-verbatim quote.
2. **Representation defect:** rejecting a quote because the displayed evidence has retrieval-oriented transformations that the prompt does not explain and the validator does not normalize.

The current artifacts cannot prove which label applies to each question. A remediation that simply relaxes matching to “semantic” or fuzzy matching would violate the evidence requirement and is not recommended. A safer approach is to make the quote representation explicit and exact, or to normalize only documented rendering artifacts on both sides while retaining exact-substring behavior.

Existing tests already cover the relevant mechanics:

- `tests/relay/test_citations.py:12` — valid quote offsets and metadata.
- `tests/relay/test_citations.py:31` — fabricated quote, missing source, numeric mismatch, and control/free-form rejection.
- `tests/relay/test_citations.py:50` — only complete validated claims are published.
- `tests/relay/test_citations.py:89` — a valid claim is emitted before a later failure; the invalid claim is not published.

A local synthetic reproduction confirmed the A4/A9 mechanism: a valid table claim was emitted, then a prose sentence triggered exactly `Expected a structured answer object.` This reproduces the parser behavior, not the original model text.

## Observability gap

This is the most important secondary finding.

For a failed turn, the saved result contains `displayed_characters` and the error, but not:

- the raw streamed buffer at the moment of failure;
- the text after the last complete object for `stream_format`;
- the candidate claim or quote that caused `citation_validation`;
- the model's full response or hidden reasoning;
- a copy of the first claim that was displayed before a later failure.

`ClaimStream` raises without exposing `self.buffer`, and the orchestrator catches the error and clears `answer` and `claims`. The evaluator writes only `result.to_dict()` and attempt metadata.

Consequences:

- The report can prove the rejection mechanism but not the exact rejected quote.
- The report can prove the stream framing violation but not the exact suffix.
- A future investigator cannot distinguish paraphrase from typography mismatch without rerunning Groq.
- Any claim that all five citation failures share one exact cause would be unsupported.

A diagnostic improvement should capture failure context before clearing, for example:

- the stream buffer at exception time;
- the last complete object and parsed claim;
- the failing quote and source ID;
- the number of displayed characters;
- a redacted/truncated copy of the response.

This should be an evaluation/diagnostic artifact only. It should not alter validation or create a path for failed content to be treated as an answer.

## Recommended remediation

Nothing below has been implemented.

### P0: make future failures diagnosable

1. Preserve failure context in the evaluator before result clearing:
   - raw stream buffer at exception;
   - last complete record;
   - candidate claim/quote/source ID;
   - display count and parser state.
2. Add a regression test that a failed stream retains diagnostic context while `result.answer` and `result.claims` remain empty.
3. Keep the diagnostic artifact separate from user-visible answers and from the existing raw result fields that downstream consumers may rely on.

### P1: align quote representation without weakening validation

4. Decide whether evidence text should be optimized for retrieval, exact quotation, or both. If both are needed, preserve a separate canonical quote text rather than applying retrieval-oriented transformations to the text that the validator treats as the source of truth.
5. Revisit extraction-time `dehyphenate`: either keep original hyphenation for quote text, or apply the same documented dehyphenation to both the quote and source before matching. The latter is conservative but must be tested against false positives.
6. Make table and math evidence quote-friendly:
   - document that table quotes must include the exact pipe-separated row, or provide cell-level citations;
   - document the `^{...}` superscript convention and the line-broken fraction form;
   - add prompt examples that copy those exact forms.
7. Validate the audit annotations against production chunk text. Some annotated quotes are semantic rather than literal substrings. Use exact-text annotations for validator tests and keep semantic annotations separate.

### P1: strengthen protocol compliance

8. Add few-shot output examples for:
   - a pipe-separated table row;
   - a superscript math quote;
   - a dehyphenated source word;
   - a two-part answer using multiple claim objects;
   - an A4-style conflict represented as structured claims, not prose.
9. Add a structured conflict representation or explicit claim pattern so “expose source conflicts” can be satisfied without leaving JSON Lines.
10. Use provider-supported structured output/JSON-schema decoding if available. If not available, consider one bounded repair attempt that returns the parser error and exact source excerpt and requires a full JSON-only retry. Preserve both attempts and do not accept unvalidated text.
11. Keep the parser strict. Do not accept prose, Markdown fences, or unvalidated fallback answers as success.

### P2: controlled retry and verification

12. Consider a single repair retry for `citation_validation` and `stream_format`. This is a behavior change, not a validation relaxation, and should be approved separately.
13. Add targeted regression tests for:
    - A2 superscript/Unicode quote variants;
    - A8 dehyphenated versus hyphenated quote variants;
    - A10 table pipes, percentages, and arrow variants;
    - A11 `x` versus `×`, singular/plural, and “times” variants;
    - A12 `1/√dk` versus the exact split-fraction and `^{√}dk` forms;
    - A4 table claim plus structured conflict claims;
    - A9 two-part structured answer;
    - failure-context retention.
14. Re-run only the affected questions after fixes are approved. Preserve the current raw artifacts first and do not overwrite the Phase 5 evidence.

### Acceptance criteria for a future fix

- Fabricated, paraphrased, or non-retrieved citations are still rejected.
- Numeric support is still checked.
- The seven questions either produce valid cited answers or fail with a newly documented, evidence-based limitation.
- A4 exposes both `41.8` (Table 2) and `41.0` (prose) without silently resolving the conflict.
- A9 reports both the threshold `0.5` and `p1 = 1.0`.
- Failure artifacts retain enough context to identify the exact rejected quote and stream suffix.
- Existing tests, new regression tests, lint, and format checks pass.

## Open questions

- What exact quote did the model generate for A2, A8, A10, A11, and A12?
- Did the model paraphrase, use a different notation, or quote a different source form?
- What exact non-JSON content followed the first claim in A4 and A9?
- Would a structured conflict claim have satisfied A4's system instruction and output contract?
- Is provider-side JSON-schema/grammar enforcement available for `openai/gpt-oss-20b` in the current client?
- Can evidence text preserve exact quotation while retaining the retrieval benefits of dehyphenation and table normalization?
- Should the audit's semantic evidence quotes be rewritten as exact production substrings?

Until those questions are answered, the only defensible conclusion is the mechanism-level one: five exact-quote rejections with confirmed source-format hazards, and two framing violations after validated claims. The exact per-question model text is not recoverable from the saved artifacts.
