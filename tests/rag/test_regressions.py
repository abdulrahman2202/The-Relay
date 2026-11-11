import re

import pytest

from retrieval.chunking import chunk_paper
from retrieval.config import RagConfig
from retrieval.models import PageText, SectionSpan, content_hash


def test_moshi_numbers_hyphenation_and_signed_exponents(supplied_documents):
    moshi = supplied_documents[1]
    assert "theoretical latency of 160ms, 200ms in practice" in moshi.pages[0].text
    table = moshi.pages[7].text
    assert "10^{−4}" in table
    assert "10^{−}^{4}" not in table
    quantizers = moshi.pages[10].text
    assert "Q = 8" in quantizers and "NA = 2048" in quantizers
    assert "12.5Hz" in quantizers and "1.1kbps" in quantizers


def test_table_rows_preserve_decimal_values_and_paper_conflicts(supplied_documents):
    attention = supplied_documents[0].pages[7]
    assert "Transformer (big) | 28.4 | 41.8" in attention.text
    assert "2.3 · 10^{19}" in attention.text
    assert "BLEU score of 41.0" in attention.text  # Original source conflict remains visible.
    hnet = supplied_documents[2].pages[16]
    assert "Transformer | 3.62 | T15 | 0.7404 | 0.599" in hnet.text
    assert "H-Net (2-stage) | 5.81 | T30 | 0.7032 | 0.663" in hnet.text
    assert any(region.kind == "table" for region in hnet.regions)


def test_section_labels_reject_audited_table_and_prose_false_positives(supplied_documents):
    for doc in supplied_documents:
        for page in doc.pages:
            for section in page.sections:
                assert not re.match(
                    r"^(?:38\.1|1920|56\.4|A natural question|50 continuations)",
                    section.section or "",
                )
    moshi = supplied_documents[1]
    assert any(
        s.section == "5.3 Ablations on generative modeling" for s in moshi.pages[24].sections
    )
    assert any(s.section == "5.5 Spoken question answering" for s in moshi.pages[28].sections)


def test_rotated_figure_labels_are_retained_and_math_uncertainty_is_reported(supplied_documents):
    assert "block=32" in supplied_documents[1].pages[59].text
    assert "block=256" in supplied_documents[1].pages[59].text
    hnet = supplied_documents[2]
    assert "Validation Bits-per-byte" in hnet.pages[12].text
    assert "bt = 1{pt ≥0.5}" in hnet.pages[5].text
    assert not re.search(r"[\x00-\x08\x0b-\x1f]", hnet.pages[5].text)
    assert any(i.kind == "math_layout_warning" and i.page_number == 6 for i in hnet.issues)


def test_boundary_chunks_keep_complete_measurement_sentences(small_documents, tokenizer):
    from dataclasses import replace

    text = (
        "Background discusses spoken dialogue and previous systems. "
        "Moshi latency is 160 ms theoretically and 200 ms in practice. "
        "More unrelated detail follows."
    )
    page = PageText(1, text, (SectionSpan(0, len(text), "Abstract"),), content_hash(text))
    document = replace(small_documents[1], pages=(page,))
    chunks = chunk_paper(document, tokenizer, RagConfig(chunk_size=17, overlap=3))
    assert any("160 ms theoretically and 200 ms in practice" in chunk.text for chunk in chunks)
    assert all(chunk.token_count <= 17 for chunk in chunks)


@pytest.mark.parametrize(
    "settings",
    [
        {"strategy": "unknown"},
        {"chunking": "unknown"},
        {"bm25_b": float("nan")},
        {"candidate_k": 0},
        {"rrf_constant": True},
        {"bm25_k1": False},
    ],
)
def test_query_and_chunking_configuration_validation(settings):
    with pytest.raises(ValueError):
        RagConfig(**settings)
