import json
from dataclasses import replace

import pytest

from retrieval.chunking import chunk_paper
from retrieval.config import PRESETS, RagConfig
from retrieval.models import ExtractedPaper, PageText, SectionSpan, content_hash


@pytest.mark.parametrize(
    "settings",
    [
        {"chunk_size": 0},
        {"chunk_size": True},
        {"overlap": -1},
        {"overlap": 300},
        {"top_k": 0},
        {"top_k": 1.5},
        {"batch_size": 0},
    ],
)
def test_invalid_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        RagConfig(**settings)


def test_overlap_tail_and_deterministic_ids(small_documents, tokenizer):
    config = RagConfig(chunk_size=5, overlap=2)
    chunks = chunk_paper(small_documents[0], tokenizer, config)
    assert [(c.token_start, c.token_end) for c in chunks] == [(0, 5), (3, 8), (6, 11), (9, 12)]
    assert chunks[-1].text.endswith("kappa")
    repeated = chunk_paper(small_documents[0], tokenizer, replace(config, top_k=20))
    assert chunks == repeated
    changed = chunk_paper(small_documents[0], tokenizer, replace(config, overlap=1))
    assert chunks[0].chunk_id != changed[0].chunk_id


def test_cross_page_and_section_metadata(small_documents, tokenizer):
    first = "alpha beta gamma"
    second = "delta epsilon zeta"
    pages = (
        PageText(2, first, (SectionSpan(0, len(first), "Introduction"),), content_hash(first)),
        PageText(4, second, (SectionSpan(0, len(second), "Methods"),), content_hash(second)),
    )
    document = ExtractedPaper(small_documents[0].paper, 4, pages, ())
    chunks = chunk_paper(document, tokenizer, RagConfig(chunk_size=4, overlap=1, chunking="fixed"))
    first_chunk = chunks[0]
    assert first_chunk.pages == (2, 4)
    assert [source.section for source in first_chunk.sources] == ["Introduction", "Methods"]
    assert first_chunk.text[first_chunk.sources[1].start_char :] == "delta"
    metadata = first_chunk.metadata()
    assert metadata["page_start"] == 2
    assert metadata["page_end"] == 4
    assert json.loads(metadata["page_numbers_json"]) == [2, 4]
    assert json.loads(metadata["sections_json"]) == ["Introduction", "Methods"]
    assert metadata["arxiv_id"] == "1706.03762"
    assert metadata["version"] == 7
    assert metadata["paper_title"] == "Attention Is All You Need"
    assert metadata["source_url"].endswith("1706.03762v7")
    for chunk in chunks:
        assert all(0 <= s.start_char < s.end_char <= len(chunk.text) for s in chunk.sources)


@pytest.mark.parametrize("size,k", [(300, 3), (600, 4), (900, 5)])
def test_requested_presets_preserve_full_coverage(size, k, small_documents, tokenizer):
    text = " ".join(f"term{i}" for i in range(1850))
    page = PageText(1, text, (SectionSpan(0, len(text), "Methods"),), content_hash(text))
    document = replace(small_documents[0], pages=(page,))
    chunks = chunk_paper(document, tokenizer, PRESETS[size])
    assert PRESETS[size].top_k == k
    assert all(0 < len(tokenizer.encode(c.text)) <= size for c in chunks)
    assert all(c.token_count == len(tokenizer.encode(c.text)) for c in chunks)
    recovered = set().union(*(set(c.text.split()) for c in chunks))
    assert recovered == set(text.split())
    assert chunks[-1].text.endswith("term1849")


def test_exact_window_has_no_redundant_tail(small_documents, tokenizer):
    chunks = chunk_paper(small_documents[0], tokenizer, RagConfig(chunk_size=12, overlap=3))
    assert len(chunks) == 1


def test_duplicate_pages_do_not_create_extra_chunks(small_documents, tokenizer):
    document = small_documents[0]
    duplicate = replace(document.pages[0], page_number=2, duplicate_of=1)
    repeated = replace(document, page_count=2, pages=(*document.pages, duplicate))
    assert chunk_paper(document, tokenizer, RagConfig()) == chunk_paper(
        repeated, tokenizer, RagConfig()
    )


def test_parent_heading_is_not_indexed_as_standalone_evidence(small_documents, tokenizer):
    parent = "3.2 The Helium Text Language Model\n\n"
    child = "3.2.1 Architecture\n\nHelium contains seven billion parameters."
    text = parent + child
    page = PageText(
        1,
        text,
        (
            SectionSpan(0, len(parent), parent.strip()),
            SectionSpan(len(parent), len(text), "3.2.1 Architecture"),
        ),
        content_hash(text),
    )
    doc = replace(small_documents[1], pages=(page,))
    chunks = chunk_paper(doc, tokenizer, RagConfig(chunk_size=80, overlap=0))
    assert len(chunks) == 1
    assert parent.strip() in chunks[0].text and "seven billion" in chunks[0].text
    assert len(chunks[0].sources) == 2
