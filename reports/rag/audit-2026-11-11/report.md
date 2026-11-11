**The Moshi latency miss is a retrieval-ranking failure.** The supplied PDF and the
indexed text contain both requested values, together with their explanation. For
the saved question, the answer-bearing 300-token chunk ranks 24th in both Chroma
and exact cosine search. Retrieving ten vector neighbors still misses it. BM25
ranks that chunk second; the tested hybrid ranks it sixth. Larger chunks recover
this particular answer but introduce other misses and consume more context.

This audit was completed on 11 November 2026. It inspected
[pipeline.py](../../../src/retrieval/pipeline.py), its extraction, chunking,
embedding, index and metadata dependencies, [tests/rag](../../../tests/rag),
[docs/rag.md](../../../docs/rag.md), and the saved
[ingestion](../ingestion-300.json), [retrieval](../retrieval-300.json) and
[validation](../validation.md) records. No existing implementation, tests,
documentation, PDFs, saved results or production index were changed. All 39
hash-protected existing files remain unchanged; see
[preservation-before.json](preservation-before.json) and
[preservation-after.json](preservation-after.json). The existing working tree
already contained uncommitted Phase 2 work; it was preserved.

The production Chroma database was copied into a separate directory under
`.cache/`. The existing 300-token collection was queried from that copy. The
unchanged ingestion code created the 600- and 900-token collections there.
Embeddings used the cached local MiniLM model on CPU, with Python socket
connections blocked during the experiment. No LLM or external embedding service
was used. The previously recorded 59 passing tests and Ruff results were
inspected, not rerun or reported as new audit test results.

**Paper identity and physical-page provenance check out.** The corpus validator
accepted the exact PDF checksums and first-page arXiv version stamps. These are
the only papers in all three collections:

| Supplied paper | arXiv ID/version | Physical PDF pages | Chunks: 300 / 600 / 900 |
| --- | --- | ---: | ---: |
| Attention Is All You Need | 1706.03762v7 | 15 | 38 / 17 / 11 |
| Moshi: a speech-text foundation model for real-time dialogue | 2410.00037v1 | 66 | 192 / 88 / 57 |
| Dynamic Chunking for End-to-End Hierarchical Sequence Modeling | 2507.07955v2 | 39 | 150 / 68 / 44 |
| Total | Exactly three papers | 120 | 380 / 173 / 112 |

All 665 stored records matched regenerated deterministic IDs, text and metadata.
An additional check mapped all 1,403 source spans back to their extracted physical
pages without a text, page, identity or citation-URL mismatch. Source-span offsets
are relative to the returned chunk; top-level `char_start`/`char_end` offsets are
relative to the concatenated paper. Citations list the actual physical pages and
include the correct version. The URL opens the first cited page, which can be
less precise than the exact evidence location in a multi-page chunk. These checks
establish provenance consistency, not the correctness of every section label or
the sufficiency of a citation for a particular answer. Details are in
[index-inspection.json](index-inspection.json) and
[citation-checks.json](citation-checks.json).

Section classification has confirmed errors. For example:

| Source | Stored section label | Actual source content |
| --- | --- | --- |
| Attention, p. 8 | `38.1 3.3 · 1018` | BLEU and training-cost cells in Table 2 |
| Moshi, p. 25 | `1920 5.3 Ablations on generative modeling` | A table's final value was prepended to the following heading |
| Moshi, p. 29 | `56.4 5.5 Spoken question answering` | Another table's final value was prepended to a heading |
| H-Net, p. 19 | `A natural question arises: does the importance of Mamba layers (i) stem specifically from processing fine-grained byte` | An ordinary paragraph, not an appendix heading |

The causes are visible in `extraction.py`: numbered-heading recognition accepts
some numeric cells and prose beginning with a capital letter, and an immediately
preceding numeric line can be attached to a heading. Section labels also carry
forward until another heading is recognized. Agreement between stored metadata
and the extractor therefore does not establish semantic section accuracy. These
errors do not change the physical-page citations, but would affect section-based
filtering or expansion.

**The saved Moshi query was reproduced without changing its wording:**

> What are the theoretical and practical latency of Moshi full-duplex speech dialogue?

The repeated 300-token/top-3 search returned the same chunk IDs, in the same order,
as the saved result:

| Rank | Chunk ID prefix | Physical pages | Cosine similarity | Returned content |
| ---: | --- | --- | ---: | --- |
| 1 | `37c61f5a49dd571c` | Moshi 1 | 0.649399 | Title, authors and the start of the abstract; ends before the latency values |
| 2 | `3285526998dc6bff` | Moshi 6, 7 | 0.643955 | Prior dialogue systems, full-duplex architecture and model overview |
| 3 | `30d9d824cdd44192` | Moshi 2 | 0.612977 | Pipeline limitations, turn taking and overlapping speech |

The first hit contains this statement about earlier pipeline systems:

```text
Such frameworks cannot emulate the experience of real conversations. First, their complex-
ity induces a latency of several seconds between interactions.
```

That is relevant background, but it does not state Moshi's numerical latency.
The answer is in another chunk, with full ID
`bbac4b1202c11faa807addf7c32cdee7584a5a90d2c14652e5a7c0920fb1a40c`.
Its exact extracted text includes:

```text
sulting model is the first real-time full-duplex spoken large language model, with a theoret-
ical latency of 160ms, 200ms in practice, and is available at github.com/kyutai-labs/moshi.
```

The values and sentence are on
[Moshi v1, physical p. 1](https://arxiv.org/pdf/2410.00037v1#page=1).
The chunk spans pages 1–2, token positions `[250, 550)` and paper character
positions `[1110, 2522)`. Both values and their immediate explanation survive in
that single chunk. Its embedding includes them. The first chunk, `[0, 300)`,
keeps the title and early abstract while ending before these values; the answer
chunk includes the abstract's tail plus unrelated introduction material.

| Chunk size | Vector rank of the chunk containing both values | BM25 rank | Hybrid RRF rank |
| ---: | ---: | ---: | ---: |
| 300 | 24 | 2 | 6 |
| 600 | 2 | 1 | 1 |
| 900 | 3 | 1 | 2 |

The full 600-token answer chunk is
`b22dcbdfe3e480779ba1ad9c85bed97b32fadf1449b4c04f21f6ed7ba490bd98`;
the 900-token answer chunk is
`29f9d6ffa5a6fb65d50717f3119c3468bcac7a74552f5c5f86ed775a05a28608`.
Full text, metadata, ranks and embedding diagnostics are saved in
[moshi-diagnostics.json](moshi-diagnostics.json).

The evidence supports these root causes and contributing factors:

1. Vector similarity favors passages describing the topic over the passage that
   supplies the requested measurements. Paper/page matches consequently overstate
   answer coverage. The integration assertion in `test_integration.py`, lines
   39–45, only requires an expected paper/page intersection and nonempty citations.
   It does not require either numerical value.
2. Fixed token boundaries fragment the abstract and allow unrelated sections to
   share one embedding. In this example the values are not separated from their
   immediate explanation, but they are separated from the title and much of the
   surrounding abstract. A 50-token overlap does not preserve that complete unit.
3. MiniLM's long-chunk pooling can dilute a small relevant passage. The answer
   chunk's first 254-token window contains both values and has query cosine
   0.531330. Its remaining 46-token window has cosine 0.089829 and discusses early
   conversational pipelines. Pooling lowers the chunk score to 0.507445. This is
   a measured contribution, not proof that changing pooling alone fixes the rank.
4. Line-end hyphenation preserves `theoret-\nical`, weakening lexical matching and
   changing the embedding input. Joining line-end hyphens in this candidate alone
   changes its dense cosine to 0.539671. That diagnostic is not a whole-corpus
   reranking result; the same normalization lowered the answer candidate's dense
   score for the larger two chunk sizes.

There is no evidence of silent embedding truncation here. The implementation
processes every token in windows of at most 254 content tokens, normalizes each
window vector, averages with token-count weights, then normalizes the result.
Chroma's top ten exactly matched exhaustive cosine ranking for all 51
question/configuration pairs, with no differences between direct cutoff searches
and prefixes of the top-50 search. The latency candidate's exact rank is also 24.
Restricting the 300-token search to Moshi still fails to return it in the top ten.
Changing the ANN index or adding a paper filter is therefore not a demonstrated
fix for this example.

**Extraction preserves the latency numbers, but does not preserve all numerical
structure.** All 120 pages produced text; no empty-page, duplicate-page or
extraction-failure issues were reported. That result cannot establish full table,
equation or figure fidelity. Automated checks across all extracted pages and
removed text, together with manual inspection of selected PDF renders, found the
following:

| Content | Actual observation | Consequence |
| --- | --- | --- |
| Prose quantities | Moshi p. 1 keeps `160ms, 200ms in practice`; p. 11 keeps `Q = 8`, `NA = 2048`, `12.5Hz`, `1.1kbps` | These misses can be investigated at ranking/chunk level |
| Tables | Attention Table 2 and H-Net Table 4 become sequences of lines; values remain, but cell boundaries, blank cells and column structure are not represented | Values can lose their model, metric or column association |
| Exponents | Attention p. 8 renders training cost as `2.3 · 1019` instead of preserving the exponent in 2.3 × 10^19 | Keeping digits does not preserve the number's mathematical meaning |
| Equations | Attention p. 4 puts `√dk` after `)V` and equation number `(1)`; H-Net p. 6 reorders the routing formula and retains U+0012/U+0013 control characters | General equation reconstruction is unreliable even when a simple threshold is still readable |
| Rotated text | The filter discards all predominantly vertical lines, including genuine figure labels | Figures lose content along with the intended arXiv margin stamp |

Excluding the arXiv stamps, the rotation filter removes 282 text lines from
Attention figures on pp. 13–15, including two `2009` labels; 30 from Moshi figures
on pp. 34, 59 and 60, including `block=32` and `block=256` three times each; and two
`Validation Bits-per-byte` labels from H-Net pp. 13 and 16. This is an actual
content-loss mechanism. There is no OCR or image-content extraction fallback.

Digit counts in retained horizontal text matched the normalized extraction:
1,485 for Attention, 8,358 for Moshi and 6,493 for H-Net. This check excludes
already-filtered lines and cannot detect exponent changes, column shifts or
missing image-only content. It must not be reported as numerical extraction
accuracy. Raw removals and counts are in
[extraction-inspection.json](extraction-inspection.json); selected PDF renders
are in [figures](figures).

Two numerical inconsistencies are present in the PDFs themselves. Attention p. 8
Table 2 gives EN-FR BLEU **41.8**, while the following prose says **41.0**. H-Net
p. 17 Figure 6 says approximately **3.6× less data**, while nearby prose says
**3.6× the amount of data**; the figure and p. 37 discussion describe improved
data efficiency. These are not extraction errors. An answer should identify the
requested table/figure and flag conflicting source statements, rather than
silently selecting a number. The evaluation questions explicitly name Table 2
and Figure 6 for this reason.

Chunk boundaries are based on WordPiece positions, without sentence, paragraph,
table or section constraints. They can cut inside words and span several
sections or pages. The observed counts of chunks starting/ending between two
alphanumeric characters were:

| Chunk size | Total chunks | Starts inside a word/number | Ends inside a word/number |
| ---: | ---: | ---: | ---: |
| 300 | 380 | 53 | 46 |
| 600 | 173 | 34 | 31 |
| 900 | 112 | 10 | 12 |

These are boundary counts, not counts of proven answer failures; a chunk can be
counted at both ends. Evidence sometimes needs multiple chunks: for example,
Attention's optimizer parameters and warmup count, or a table's labels and data
rows. The scoring below credits complete evidence across the union of returned
chunks, rather than requiring all facts in one chunk.

**Evaluation used the same questions and evidence rules for every configuration.**
There are 12 answerable questions, four per paper, including all three existing
smoke questions, plus five unsupported questions. Query strings and initial
annotations were saved before running the retrieval comparisons in
[questions.json](questions.json). This is a small diagnostic set, not a held-out
benchmark or a representative sample of future user questions.

The metric is **complete annotated evidence coverage**: a question counts only
when every required factual unit has a valid supporting alternative covered by
the union of the returned source spans from the correct paper. Table evidence
requires named rows and column labels. This measures retrievable evidence, not
generated-answer accuracy, citation entailment by an LLM, precision or nDCG.

Manual review after retrieval found valid alternate evidence missing from the
initial annotations. The recorded additions cover Attention's base-model row in
Table 3, repeated Helium facts, alternate Inner Monologue descriptions and H-Net's
Figure 1 discussion. Helium's 2.1T-token total can also be supported by the explicit
500k training steps × 4.2M tokens per step; that arithmetic alternative is credited
only with the model/column identity. Questions, embeddings, ranking parameters
and ranked outputs were unchanged. All main results below use the reviewed
annotations. The original scores remain available, alongside
[annotation-review.json](annotation-review.json),
[annotation-effects.json](annotation-effects.json) and
[evidence-reviewed.json](evidence-reviewed.json). This review improves annotation
completeness but does not make the set independent of the audit.

The controlled settings were 50-token overlap; the same PDFs and local model;
no paper filter for the primary comparison; and cutoffs of 3, 5 and 10 plus each
preset's native cutoff. The model was
`sentence-transformers/all-MiniLM-L6-v2`, revision
`c9745ed1d9f207416be6d2e6f8de32d1f16199bf`, with 384-dimensional embeddings,
CPU inference, one Torch thread and seed 0. Exact dependency versions and
collection fingerprints are retained in the ingestion reports and index
inspection. See [protocol.json](protocol.json) for the experiment settings.

Three retrievers were compared over exactly the same chunks:

- The existing Chroma cosine search, unchanged.
- BM25 with k1 = 1.5 and b = 0.75, fixed stopwords, Unicode normalization,
  line-end dehyphenation and decimal/quantity-unit token splitting. It indexes
  chunk text without a metadata title boost.
- Equal-weight reciprocal-rank fusion of the first 50 vector and 50 BM25
  candidates, using the fixed formula `sum(1 / (60 + rank))`. No reranker was used.

No ranking parameters were tuned after observing the results. BM25 and fusion
were isolated audit experiments; they were not added to the application.

| Retriever | Chunk tokens | Complete evidence @3 | @5 | @10 |
| --- | ---: | ---: | ---: | ---: |
| Vector | 300 | 10/12 | 11/12 | 11/12 |
| Vector | 600 | 11/12 | 12/12 | 12/12 |
| Vector | 900 | 10/12 | 11/12 | 12/12 |
| BM25 | 300 | 11/12 | 11/12 | 12/12 |
| BM25 | 600 | 12/12 | 12/12 | 12/12 |
| BM25 | 900 | 11/12 | 12/12 | 12/12 |
| Hybrid RRF | 300 | 10/12 | 10/12 | 12/12 |
| Hybrid RRF | 600 | 12/12 | 12/12 | 12/12 |
| Hybrid RRF | 900 | 11/12 | 12/12 | 12/12 |

For a per-question view, each cell below is the smallest vector-result prefix
containing all required evidence. A value above a cutoff means that cutoff
misses required evidence. This also makes the top-3/5/10 outcomes individually
reviewable:

| ID and evidence sought | 300 tokens | 600 tokens | 900 tokens |
| --- | ---: | ---: | ---: |
| A1: inverse-square-root attention scaling and small gradients | 1 | 2 | 1 |
| A2: Table 2 Transformer (big) BLEU, 28.4 / 41.8 | 2 | 3 | 4 |
| A3: base Transformer, 8 heads and 64-dimensional keys/values | 1 | 1 | 2 |
| A4: Adam 0.9 / 0.98 / 10^-9 and 4,000 warmup steps | 2 | 1 | 1 |
| M1: Moshi theoretical/practical latency, 160 / 200 ms | 24 | 2 | 3 |
| M2: Mimi, 8 quantizers / 2,048 entries / 12.5 Hz / 1.1 kbps | 3 | 5 | 3 |
| M3: Helium, 7B parameters and 2.1T pretraining tokens | 4 | 1 | 6 |
| M4: Inner Monologue, aligned text before audio | 2 | 1 | 1 |
| H1: learned content/context-dependent chunking | 1 | 1 | 1 |
| H2: boundary threshold >= 0.5 and initial probability 1.0 | 3 | 3 | 3 |
| H3: Table 4 XWinograd-zh accuracy, 0.599 / 0.663 | 1 | 1 | 1 |
| H4: Figure 6, approximately 3.6× greater data efficiency | 3 | 1 | 1 |

The Mimi failure at native 600/4 is another numerical ranking miss. The first
four hits concern model compression or watermarking. Rank 5, chunk
`8b357b352d92e79c` on Moshi pp. 10–11, contains the needed passage:

```text
We use Q = 8 quantizers, each with a codebook size of NA = 2048.
At 12.5Hz, this represents a bitrate of 1.1kbps.
```

For Helium with 900-token chunks, complete evidence first appears at rank 6;
the native top-5 misses it. With 300-token chunks, vector search completes this
question at rank 4, BM25 at rank 2, but RRF only at rank 7. That explains the
300-token hybrid regression at top-5: fusion can demote the evidence that one
retriever ranks well. BM25 also misses the complete head/dimension evidence at
300/top-3 and top-5, although vector retrieval gets it at rank 1. Neither method
dominates every question.

A separate lexical ablation omitted line-end dehyphenation. At 300/top-3,
complete-evidence coverage was 10/12, compared with 11/12 for normalized BM25;
Moshi latency was the changed case. This measures the effect of this specific
lexical normalization on this set. It is not a claim that dehyphenating all dense
embedding inputs improves them.

**Native preset comparisons must include the context budget.** The application
uses a 4,096-token default in `build_context`, counts citation headers and
separators, and stops at the first complete hit that would exceed the budget.
The audit applied that same policy; no generation was performed.

| Existing vector preset | Retrieved complete evidence | Complete evidence in bounded context | Mean cited-context tokens | Chunks retained in context |
| --- | ---: | ---: | ---: | ---: |
| 300 tokens / retrieve 3 | 10/12 | 10/12 | 981.5 | 3 |
| 600 tokens / retrieve 4 | 11/12 | 11/12 | 2,532.3 | 4 |
| 900 tokens / retrieve 5 | 11/12 | 11/12 | 3,737.8 | 4 |

For these runs, top-10 keeps ten 300-token chunks, six 600-token chunks or four
900-token chunks. Vector 900/top-10 retrieves complete evidence for 12/12, but
the bounded context contains it for only 11/12: Helium's evidence at rank 6 is
excluded. Raising retrieval k does not guarantee that the additional evidence
reaches a future LLM. Context counts use MiniLM's tokenizer; a future generation
model's tokenizer and prompt overhead need their own budget calculation.

The measured results make 600-token lexical/hybrid retrieval a promising
candidate for further evaluation. They do not establish a generally best
configuration. The sample is small, annotations were manually reviewed, and
context cost differs substantially. Full ranks, scores, returned IDs and context
IDs are in [rankings.json](rankings.json),
[coverage-reviewed.csv](coverage-reviewed.csv) and
[summary-reviewed.json](summary-reviewed.json). Join ranked IDs with
[chunks-300.json](chunks-300.json), [chunks-600.json](chunks-600.json) or
[chunks-900.json](chunks-900.json) to inspect exact passages. Additional aggregate
checks are in [verification.json](verification.json).

**Five questions should receive an explicit “not reported in the supplied
papers” response.** These are unsupported by this fixed corpus, rather than
necessarily unanswerable elsewhere:

| ID | Question | Why the retrieved material cannot answer it |
| --- | --- | --- |
| U1 | Moshi p95 end-to-end latency on iPhone 15 Pro running iOS | No such device-specific percentile measurement is reported; the generic 160/200 ms statement cannot substitute |
| U2 | Benchmark results for a 70-billion-parameter H-Net | No such experiment is reported; p. 23 discusses FLOP matching to a 1.3B Transformer and validation at larger sizes as future work |
| U3 | Original Attention Transformer's MMLU accuracy | Attention does not report MMLU; other papers' model scores have different attribution |
| U4 | Commercial Moshi API price per million speech tokens in November 2026 | The papers do not give that dated commercial price |
| U5 | Moshi's BLEU improvement over H-Net on WMT2014 EN-FR | The requested paired benchmark comparison is absent; Transformer translation results are not an answer |

Corpus searches and examination of nearby passages support these judgments.
For example, H-Net's `70B` occurrences are on p. 16 under **Total Training Bytes**,
not model size. Its p. 23 text says: “The largest models in this paper were
FLOP-matched to the equivalent of a 1.3B parameter Transformer.” For U5, both
300-token vector and hybrid retrieval rank the Attention p. 8 passage first,
including “our big model achieves a BLEU score of 41.0.” Its paper citation is
correct, but using that number to answer the Moshi/H-Net comparison would be an
attribution error.

All five unsupported queries returned the requested number of hits at every
tested cutoff for vector, BM25 and hybrid retrieval in all three configurations.
`search()` has no evidence-sufficiency or refusal mechanism. This observation is
not an LLM hallucination rate: the module has no answer generator.

Vector scores alone do not separate supported from unsupported questions here:

| Chunk tokens | Top-1 cosine range, answerable questions | Top-1 cosine range, unsupported questions |
| ---: | ---: | ---: |
| 300 | 0.485–0.698 | 0.407–0.637 |
| 600 | 0.413–0.748 | 0.412–0.634 |
| 900 | 0.300–0.710 | 0.414–0.595 |

In particular, the unsupported 70B H-Net question scores 0.637 at 300 tokens.
A universal cosine cutoff would either retain unsupported questions or reject
some answerable ones. BM25 and RRF scores are also ranking signals, not calibrated
answerability probabilities. Refusal evaluation needs model, metric, hardware,
date and comparison constraints, not merely overlapping words or a high score.

**Recommended follow-up work is ordered below; none is implemented.** Expected
benefits are hypotheses except where a specific audit experiment above measured
them. Approval should precede changes to the working module or collections.

| Priority | Concrete improvement | Expected benefit and trade-off |
| ---: | --- | --- |
| 1 | Add evidence-level regression fixtures for these questions, table labels/rows, numerical units, paper/version attribution and unsupported cases; add separate held-out questions | Catches the current false-positive smoke result. Annotation and maintenance cost increase; avoid tuning solely to these examples |
| 2 | Correct section recognition and target margin-stamp removal by content/position; preserve rotated body text and layout coordinates; represent table rows with headers and flag uncertain math extraction | Improves source meaning and metadata. Layout handling is more complex; automated table/math recovery needs its own accuracy evaluation |
| 3 | Evaluate sentence/paragraph/section boundaries, table-aware units and bounded neighbor expansion; retain exact provenance when normalizing line-end hyphens | Keeps measurements with explanations and nearby labels. More or larger overlapping passages can add noise, duplicates and context cost |
| 4 | Add an optional local BM25 candidate path and evaluate fusion/reranking against the vector baseline; keep the current default until held-out evidence and context results justify a change | Measured lexical gains make this promising. Naive equal-weight RRF already regressed at 300/top-5; extra indexing/ranking and any local reranker add complexity and latency |
| 5 | Make context selection aware of evidence coverage and budget, deduplicate overlap and preserve citations during bounded expansion | Reduces loss between retrieval and delivered context. Selection is more complex than taking a prefix and must be evaluated separately from retrieval |
| 6 | Expose evidence sufficiency and source-conflict information for a future answer layer, with explicit refusal tests | Prevents substituting unrelated model/metric numbers. Conservative decisions may increase false refusals; calibration needs additional supported and unsupported cases |

For implementation review, the first change set should freeze the evidence
regressions and correct the demonstrated extraction/section issues. Chunking and
hybrid retrieval should remain separately configurable experiments so their
effects can be measured independently. A new local reranker or an OCR/math parser
would require its own measured justification. Any later change to extracted text,
chunking or embeddings should use a new pipeline fingerprint and separate
collection, preserving the current baseline.

The scripts and saved artifacts support local reproduction in the existing
virtual environment. To rescore the saved rankings using the reviewed evidence,
without loading an embedding model or writing to an index:

```powershell
.venv\Scripts\python.exe reports\rag\audit-2026-11-11\score_reviewed.py
```

To repeat retrieval using the retained scratch database recorded in
[state.json](state.json), then rescore:

```powershell
.venv\Scripts\python.exe reports\rag\audit-2026-11-11\run_audit.py
.venv\Scripts\python.exe reports\rag\audit-2026-11-11\score_reviewed.py
```

These commands rewrite audit outputs. The full runner checks the original-file
hashes, requires its scratch path to be under the repository's `.cache/`, and
requires the copied 300-token collection there. It reuses/creates only scratch
collections. The cached pinned model and the supplied PDFs are prerequisites.
For a clean repeat elsewhere, first copy the baseline database into a fresh
scratch directory and update a copied audit folder's `state.json`; do not direct
the experiment at the production database. The scripts are experiment artifacts,
not production retrieval features.

The audit does not establish full-corpus table/math accuracy, generated-answer
accuracy, calibrated refusal performance, retrieval latency under load or a
production-optimal configuration. No implementation changes should be made until
this report and the proposed scope are approved.
