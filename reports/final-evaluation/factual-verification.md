# Factual verification against the supplied PDFs

Review date: 2026-11-12. This is a local source review, separate from historical answer grading. No external model or API was called. Original Phase 5 and Phase 5.3 JSON/CSV files and `manual-grading.csv` are unchanged.

## Sources and method

All page references below are **physical PDF pages**, counted from 1. The files' SHA-256 hashes and first-page arXiv stamps match `src/retrieval/catalog.py`:

| Local source | Exact version | Pages | SHA-256 |
|---|---|---:|---|
| [Attention Is All You Need](../../papers/attention_is_all_you_need.pdf) | arXiv:1706.03762v7 | 15 | `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697` |
| [Moshi: a speech-text foundation model for real-time dialogue](../../papers/moshi.pdf) | arXiv:2410.00037v1 | 66 | `a687144cc77bea86b0c60ae800ccb1d3e0816033fa5c7960388fe29a0dbfcfac` |
| [Dynamic Chunking for End-to-End Hierarchical Sequence Modeling](../../papers/dynamic_chunking.pdf) | arXiv:2507.07955v2 | 39 | `04a2b32e6e82853cfc23c5db132750874a86cde99219ec6f664128f4aa83122f` |

The review used PyMuPDF on these original files, surrounding paragraphs, and rendered views of Attention pp. 4/8 and Dynamic Chunking pp. 6/17 to check fractions, subscripts, table columns, and figure captions. Mathematical displays below are transcriptions of the rendered equations, not quotations from the lossy extraction representation. Short prose quotations normalize line wrapping only. No outside knowledge supplies missing evidence.

The latest manual session is available only as the user's summary and metrics. Its exact questions, generated routing formula, source IDs, and complete quotations are unavailable. Earlier A8 has a three-citation count but no full answer. Source verification therefore does not establish that every generated claim or citation was correct.

## 1. Attention BLEU scores — A4 and latest BLEU session

**Source:** Attention Is All You Need, arXiv:1706.03762v7, p. 8, Table 2 and section 6.1, “Machine Translation.” The table caption identifies English-to-German and English-to-French **newstest2014** tests.

| Table 2 model row | EN-DE BLEU | EN-FR BLEU |
|---|---:|---:|
| Transformer (base model) | 27.3 | 38.1 |
| Transformer (big) | 28.4 | 41.8 |

Same-page prose states: “our big model achieves a BLEU score of 41.0” for WMT 2014 English-to-French. The EN-DE prose agrees with `28.4`. The EN-FR paragraph additionally says that the big EN-FR model used dropout `0.1` instead of `0.3`; it does not reconcile `41.0` with Table 2's `41.8`.

**Observed-answer assessment: unresolved overall.** The latest reported base/big table values and the prose value each match their respective source. The additional cited `41.8` claim cannot be audited without its quotation and does not settle the disagreement. A completely verified, single EN-FR score is not established. Both values must be attributed separately; no third value or explanation for the inconsistency is inferred.

Original Phase 5 A4 failed with `stream_format`. Phase 5.3 A4 also failed after a valid table claim and a trailing backslash; it did not expose the prose conflict in a final answer. The earlier manual A4 attempt failed numeric support validation after partial `28.4`. None becomes a correct answer because the PDF contains the expected numbers.

## 2. Adam, beta values, epsilon, and warmup — A2

**Source:** Attention Is All You Need, arXiv:1706.03762v7, p. 7, section 5.3, “Optimizer,” surrounding equation (3).

The paragraph states that the Adam optimizer used `β1 = 0.9`, `β2 = 0.98`, and `ϵ = 10^-9`. The exponent is negative nine. The schedule increases the learning rate linearly during warmup, then decreases it proportionally to the inverse square root of the step number. The same paragraph explicitly states `warmup_steps = 4000`.

**Phase 5.3 A2 assessment: correct for the question asked.** Its saved answer reports Adam, `β1 = 0.9`, `β2 = 0.98`, and `4000` warmup steps. Its S1 citation identifies this exact paper/version/page and quotes the optimizer paragraph through the warmup sentence. Epsilon was not requested by the original A2 question; its absence from that answer is not a missing requested part. This completes the previously pending factual review **here**, without rewriting Phase 5.3's historical `pending_manual_review` metadata or Phase 5's blank A2 grade.

**Earlier manual A2 second attempt: correct for the reported values.** The supplied summary also includes `epsilon=10^-9`, matching p. 7. Exact generated quotation text was not supplied, so this is a factual check of the reported content, not a fresh citation-validator result. The first attempt remains unspecified.

## 3. Routing probability, initialization, and threshold — A9

**Source:** Dynamic Chunking, arXiv:2507.07955v2, pp. 5–6; p. 6 section 2.2.1, “Routing Module,” equation (4):

\[
q_t = W_q\hat{x}_t,\qquad k_t = W_k\hat{x}_t,
\]
\[
p_t = \frac{1}{2}\left(1-\frac{q_t^\top k_{t-1}}{\lVert q_t\rVert\,\lVert k_{t-1}\rVert}\right)\in[0,1],
\qquad b_t=\mathbf{1}_{\{p_t\geq0.5\}}.
\]

The next sentence says: “where p1 = 1.0 by definition, ensuring the sequence begins with a boundary.” The adjacent representations' projected cosine similarity determines the boundary score: lower similarity gives a higher score. Footnote 7 on p. 5 cautions that the authors sometimes call it a probability but do not use it as a formal probability in the main formulation. The initialization is explicit; do not infer a nonexistent `k0` from the displayed formula.

**Earlier manual answer: partially correct.** It supplied threshold `0.5` but omitted the requested first-position probability. **Latest manual answer: partially verified; overall factual status unresolved.** The supplied `p1 = 1.0` and inclusive condition `pt >= 0.5` are correct, and the previously missing part is now reported. The user reports a formula but did not supply its exact string, so its sign, factor `1/2`, adjacent index `t-1`, normalization, and projections cannot be checked against the assistant output. No final factual grade is assigned to the whole answer. Phase 5 A9 remains an ungraded operational failure; Phase 5.3 did not attempt it.

## 4. XWinograd-zh accuracy and evaluation setting — A10

**Source:** Dynamic Chunking, arXiv:2507.07955v2, p. 17 Table 4, p. 16 “Experimental setup for Chinese and code,” p. 37 appendix E.2, and p. 4 summary.

| Table 4 Chinese model | Main architecture | Chinese validation BPB | XW-zh. accuracy |
|---|---|---:|---:|
| Transformer | T15 | 0.7404 | 0.599 |
| H-Net (space) | T19 | 0.7478 | 0.629 |
| H-Net (2-stage) | T30 | 0.7032 | 0.663 |

The requested comparison is **Transformer `0.599` versus H-Net (2-stage) `0.663`**, in the Chinese `XW-zh. acc.` column. Page 4 separately prints `59.9 → 66.3 on XWinograd-zh`. The neighboring `0.7404`/`0.7032` values are BPB, not accuracy; the code columns report no XWinograd accuracy.

Page 16 describes a 46B-token subset from FineWeb-Edu-Chinese-V2.1 and the Github subset of Pile for the Chinese/code experiments at **1.3B GPT-3 XL scale**. It specifies batch size `256`, examples of `8192` UTF-8 bytes, H-Net target ratios `N0 = N1 = 3`, byte-level H-Net, and Llama3 tokenization for the BPE Transformer. Appendix E.2 says layer counts were adjusted for compression ratios and compute targets. “Scale” should not be rewritten as identical parameter counts or architectures. Evaluation is on the **Chinese split** of the multilingual Winograd Schema Challenge. These passages do not establish a shot count or confidence interval; none is added.

**Observed accuracy-answer assessment: unresolved.** A10 failed citation validation in Phase 5 and in the earlier manual retry; Phase 5.3 did not attempt it. The latest definition answer is **correct in the XWinograd-zh scope**: p. 16 describes the Chinese split of the multilingual Winograd Schema Challenge, and p. 37 calls it a Chinese language-understanding task. XWinograd as a whole is multilingual. The definition question did not request the two accuracies and supplies no evidence that A10 now succeeds.

## 5. HG38 DNA data efficiency — A11

**Source:** Dynamic Chunking, arXiv:2507.07955v2, pp. 16–17, Figure 6 and Table 5; p. 37 appendix E.3.

Figure 6 describes the **stable training phase**. Its caption says: “Each H-Net model achieves the same pre-decay perplexity of the corresponding isotropic model with approximately 3.6× less data.” The figure label reads `3.6x more data efficient than isotropic model`. Appendix E.3 says an H-Net (1-stage) with an `M3T1` encoder achieves `3.6×` the data efficiency of an isotropic architecture.

The comparison is one-stage H-Net with either a Transformer or Mamba-2 main network against the corresponding isotropic Transformer or Mamba-2 at base-pair resolution, trained on **HG38**. The setup specifies a base-resolution learning rate `5 · 10^-3`, H-Net downsampling `N0 = 3`, and `d_model = 512`. Table 5 lists different parameter counts (`29M`, `33M`, `64M`, `66M`); this is not an equal-parameter comparison. Its final perplexities are a different measurement from the stable-phase/pre-decay comparison in Figure 6.

**Unresolved source wording:** the paragraph below the figure says H-Net achieves similar performance “with just 3.6× the amount of data,” which disagrees in direction with the caption, label, and appendix. Preserve both statements; do not silently rewrite the paragraph or claim a general compute/latency speedup.

**Observed-answer assessment: unresolved.** The recorded A11 attempts failed citation validation, and there is no complete later answer to grade. The caption supports a specifically attributed approximate data-efficiency statement; it does not turn those failed attempts into successful answers.

## 6. Scaled dot-product attention — A12

**Source:** Attention Is All You Need, arXiv:1706.03762v7, p. 4, section 3.2.1, equation (1), the following explanation, and footnote 4.

\[
\operatorname{Attention}(Q,K,V)
=\operatorname{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right)V.
\]

Queries and keys have dimension `d_k`; values have dimension `d_v`. The paper divides the query–key dot products by `sqrt(d_k)` **before** softmax and then uses the weights on `V`. It says large dot products can push softmax into regions with extremely small gradients. Footnote 4 illustrates that independent mean-zero, variance-one query/key components give a dot product with variance `d_k`. This is the stated motivation, not an unconditional proof for every learned representation.

**Observed-answer assessment: unresolved.** Original A12 failed citation validation; the earlier manual attempt generated a formula and then failed `stream_format`. The formula and complete explanation are not preserved in the supplied manual summary. No final factual grade is assigned to that incomplete answer. The later broad “Attention” refusal is a separate question, not an A12 success or a basis for grading the refusal as correct.

## 7. Moshi theoretical and practical latency — A1

**Source:** Moshi, arXiv:2410.00037v1, p. 1 abstract; p. 26 section 5.3 ablations and discussion.

The abstract reports “a theoretical latency of 160ms, 200ms in practice.” Page 26 says the final procedure settles on theoretical latency `160ms`, pretraining with acoustic delay `2` and finetuning with delay `1`. It also distinguishes a zero-delay pattern's minimum of `80ms` with Mimi tokens at `12.5Hz` from the selected final-model setting.

**Observed Phase 5 A1 answer: correct for the cited claims.** Its saved S1 quotation comes from the abstract, supporting `160 ms` theoretical and `200 ms` practical. Its additional S2 claim about the minimal Mimi-token latency is supported by p. 26, but must remain qualified as that configuration's codec-token minimum. It is not Moshi's selected practical latency. These source passages provide no iPhone/iOS-specific p95 measurement or latency percentile distribution; those cannot be filled in from the generic values. This review leaves A1's historical `correct` grade intact.

## 8. H-Net learned chunking and architecture — A8

**Source:** Dynamic Chunking, arXiv:2507.07955v2, p. 3 Figure 1 and surrounding text; pp. 4–5 section 2.1 and equations (1)–(3); pp. 6–7 section 2.2 and equations (4)–(9).

The source describes a hierarchical U-Net-like network that learns data-dependent subsampling end-to-end. Encoder, main, and decoder networks process increasingly compressed representations; the main network can itself be an H-Net for recursive stages. The defaults use Mamba-2 outer encoder/decoder layers and Transformer layers in the main network, while allowing other sequence mixers. These are architectural defaults, not a requirement that every H-Net component be a Transformer.

The router uses adjacent projected representations' cosine similarity (p. 6). The downsampler retains boundary-marked vectors; the dechunking path smooths representations with a probability-weighted EMA (p. 7 equation (5)) and upsamples back to the prior resolution, with encoder residuals (p. 5 equation (3)) and the straight-through estimator (p. 7 equations (7)/(9)). The paper reports meaningful boundaries learned without external segmentation supervision. It does not promise that every learned chunk is a word or that handcrafted BPE boundaries are reproduced exactly.

**Observed-answer assessment: unresolved.** Phase 5 A8 failed citation validation; Phase 5.3 A8 was rate-limited before model content. The earlier manual answer reportedly succeeded with three citations, but its text and quotations are unavailable. Three citations alone do not establish factual correctness or completeness. The source supports the architecture description above; it cannot establish what that unavailable answer actually said.

## Grading boundary and remaining evidence

Original Phase 5 remains **5 correct answerable answers, 8 correctly refused unanswerable questions, 7 operational failures; 13/20 graded and 7/20 ungraded**. The A2 Phase 5.3 review is now complete in this document only. The BLEU and HG38 source inconsistencies remain unresolved. Full latest routing formula/citations and earlier A8 answer/citations would be needed to complete their answer-level reviews; absent that evidence, retain the stated limitations without another API run.
