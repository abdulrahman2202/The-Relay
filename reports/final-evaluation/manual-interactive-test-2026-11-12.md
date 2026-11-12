# Manual Interactive Terminal Tests — 2026-11-12

## Environment

- Operating system: Windows 11.
- Interface: Python terminal CLI.
- Launch command: `python -m relay`.
- Provider/model: real Groq model; model identifier not supplied.

## Scope and evidence

These were interactive manual tests reported by the user, separate from Phase 5 and Phase 5.3. This report records the supplied terminal outcomes without changing those evaluations or their grades. The initial record was prepared without tests, lint, or API calls. Later local submission checks are recorded separately in [the final review](final-review-2026-11-12.md).

The outcome labels describe terminal behavior, not final factual grades. Successful means an answer was produced; partial means a requested part was omitted. Failed attempts can include text emitted before validation or stream failure. Incomplete answers receive no final factual grade.

## Recorded attempts

| Question or prompt | Attempt | Outcome | Supplied terminal result |
|---|---|---|---|
| A2 | First | Details not supplied | The first attempt did not yield the reported success; its error and metrics were not supplied. |
| A2 | Second | Successful | Adam; `beta1=0.9`, `beta2=0.98`, `epsilon=10^-9`; `4000` warmup steps; page 7. |
| A4 | Not specified | Failed | Numeric support validation failed after a partial claim of `28.4`; no complete answer. |
| A8 | Not specified | Successful; factual verification pending | Answered with three citations. Provisional pending full factual verification; no final factual grade assigned. |
| A9 | Not specified | Partial | Answered threshold `0.5`, but omitted the first-position boundary probability. |
| A10 | First | Rate-limited | The first attempt was rate limited. |
| A10 | Second | Failed | Citation validation failed after the earlier rate-limited attempt. |
| A11 | Not specified | Failed | Citation validation failed. |
| A12 | Not specified | Failed | A formula was generated, then a `stream_format` failure occurred; no complete answer. |
| Unrelated books question | Not specified | Failed | Produced `invalid_request`; exact question wording was not supplied. |
| One-word `Moshi` prompt | Not specified | Failed | Produced a `citation_validation` failure. |

## Earlier-session terminal metrics

No latency, time-to-first-token, token-usage, or retry-delay measurements were included in the earlier interactive-test summary. None are invented or copied from Phase 5 or Phase 5.3. The supplied attempt order, three-citation count for A8, and answer values are recorded above.

## Latest reported terminal session

Environment: Windows 11, Python terminal CLI, `python -m relay`, real Groq model. The model identifier, prompt version, exact question strings, full citation text, and session timestamps were not supplied. The following is the user's reported observation, not a reconstructed verbatim transcript. No new model request was made for this update.

| Topic | Observed outcome | Supplied answer details | Verification boundary |
|---|---|---|---|
| BLEU scores | Answered; overall factual verification unresolved | Transformer base: EN-DE `27.3`, EN-FR `38.1`. Transformer big: EN-DE `28.4`, EN-FR `41.8`. The prose reports EN-FR `41.0`. A further cited claim reports `41.8`. | The numbers match the respective table/prose passages, but the source conflict remains. The additional citation was not supplied in full; it does not resolve the discrepancy. This is not a completely verified answer. |
| Routing probability | Answered; previously omitted part now present | Included a routing probability formula, initial probability `p1 = 1.0`, and boundary condition `pt >= 0.5`. | Both numerical conditions match the PDF. The generated formula string and complete citations were not supplied, so the whole answer cannot yet be marked factually correct. |
| XWinograd | Answered a definition question | Identifies XWinograd as a Chinese language-understanding task and the Chinese split of the multilingual Winograd Schema Challenge. | Supported when referring specifically to XWinograd-zh. This test did not ask for XWinograd-zh accuracy and does not validate A10. |
| Attention | Refused | “The supplied papers do not provide enough evidence to answer that question.” Status: `refused`. | Broad-question refusal. Exact question wording is unavailable; no correctness grade is assigned to the refusal. It is not a successful A12 retest. |

The Attention paper, arXiv:1706.03762v7, physical PDF page 8, explicitly disagrees with itself: Table 2 reports Transformer (big) EN-FR `41.8`, while section 6.1 prose on the same page reports `41.0`. Both values remain visible; neither is silently selected. Table 2 also confirms base `27.3`/`38.1` and big EN-DE `28.4`.

Dynamic Chunking, arXiv:2507.07955v2, physical page 6, equation (4), defines `p1 = 1.0` and selects a boundary when `pt >= 0.5`. The source equation was checked locally, including its rendered mathematical layout; the missing assistant formula prevents a character-for-character comparison. See [factual verification](factual-verification.md) for the equation and per-topic findings.

### Exact supplied terminal metrics

These are **manual interactive observations, not controlled benchmark results**. They are not pooled with Phase 5, Phase 5.3, or Phase 4 measurements.

| Topic | Total | Retrieval | Input tokens | Output tokens |
|---|---:|---:|---:|---:|
| BLEU | `16.191s` | `12.353s` | `4278` | `617` |
| Routing | `1.620s` | `0.106s` | `4484` | `483` |
| XWinograd | `1.600s` | `0.104s` | `3359` | `165` |
| Attention | `1.084s` | `0.103s` | `4461` | `105` |

TTFT, generation-stage timings, validation timings, retry delays, and per-request usage breakdowns were not supplied for this session. No missing metric or retry attempt is inferred. Fuller BLEU and routing responses are observed behavior, not evidence of a statistically established improvement. The earlier partial, failed, and rate-limited attempts above remain part of the record; original evaluation grades remain unchanged.
