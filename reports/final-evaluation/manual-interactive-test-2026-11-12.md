# Manual Interactive Terminal Tests — 2026-11-12

## Environment

- Operating system: Windows 11.
- Interface: Python terminal CLI.
- Launch command: `python -m relay`.
- Provider/model: real Groq model; model identifier not supplied.

## Scope and evidence

These were interactive manual tests reported by the user, separate from Phase 5 and Phase 5.3. This report records the supplied terminal outcomes without changing those evaluations or their grades. No tests, lint, or API calls were run to prepare this report.

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

## Terminal metrics

No latency, time-to-first-token, token-usage, or retry-delay measurements were included in the supplied interactive-test summary. None are invented or copied from Phase 5 or Phase 5.3. The supplied attempt order, three-citation count for A8, and answer values are recorded above.
