# Final Submission Checklist

Date: 2026-11-12  
Status: reporting package prepared; submission remains blocked on user review items.

## Evidence and claim controls

- [x] Real Groq measurements are distinguished from simulated stand-ins.
- [x] Original Phase 5 results are kept separate from Phase 5.3.
- [x] No claim is made that all seven Phase 5 failures passed.
- [x] Phase 5.3 A2 is recorded as answered with a valid citation; factual grade remains pending.
- [x] Phase 5.3 A4 is recorded as a `stream_format` failure; the source conflict remains unresolved: English-to-German `28.4` BLEU; English-to-French `41.8` in Table 2 versus `41.0` in the prose on the same physical page 8 of Attention Is All You Need.
- [x] Phase 5.3 A8 is recorded as a real HTTP `429` rate-limit failure.
- [x] Phase 5.3 A9-A12 are recorded as `not_attempted`.
- [x] Phase 5 final grades cover 13/20 questions; 7 operational failures retain blank grades, with none classified as `wrong` or `refused_wrongly`.
- [x] Unmeasured metrics and limitations are listed in the final report.
- [x] No answer, feedback, or personal reflection was fabricated.

## Required artifacts

- [x] `final-assignment-report.md` prepared.
- [x] `final-submission-checklist.md` prepared.
- [x] `submission-readiness.md` updated with Phase 5.3 outcomes.
- [x] Phase 5.3 JSON, CSV, and verification summary preserved under `phase5-3/`.
- [x] Original Phase 1-5 evidence preserved.
- [x] Manual grading complete for the 13 graded Phase 5 questions in `manual-grading.csv`.
- [ ] User to complete the A2 Phase 5.3 factual review.
- [ ] User to review and document the unresolved A4 table-versus-prose conflict.
- [ ] User to add Vaani feedback in the marked report section.
- [ ] User to add personal assistant-work reflections in the marked report section.

## Verification

Test and lint results below are prior recorded evidence; no tests or lint were run for this grading update.

- [x] `python -m pytest -q`: `203 passed, 5 skipped` in `96.24 s`.
- [x] `python -m ruff check src tests scripts`: all checks passed.
- [x] `python -m ruff format --check src tests scripts`: 68 files already formatted.
- [x] No application code changed for this reporting step.
- [x] No new Groq API calls made for this reporting step.
- [ ] Final user review of the two-page report.
- [ ] Submission/upload, only after the user completes the open items above.

## Submission gate

Do not describe the evaluation as fully passed. Phase 5 has 5 correct answerable answers, 8 correctly refused unanswerable questions, and 7 operational failures: 13 of 20 questions graded and 7 of 20 ungraded. Phase 5.3 remains separate: A2 answered with a valid citation, with factual grade pending; A4 failed with `stream_format`; A8 failed with HTTP `429`; A9-A12 were not attempted.
