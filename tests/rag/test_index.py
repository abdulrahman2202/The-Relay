from dataclasses import replace

import pytest

from retrieval.catalog import PAPERS
from retrieval.errors import IndexingError
from retrieval.index import ChromaIndex
from retrieval.models import Chunk, SourceSpan, stable_hash


@pytest.fixture
def descriptor():
    return {"embedding": {"model": "test-only", "dimension": 3}, "chunking": {"size": 300}}


@pytest.fixture
def chunks():
    result = []
    for index, (paper, text) in enumerate(
        zip(
            PAPERS[:2],
            ["Attention uses scaled dot products.", "Moshi generates speech."],
            strict=True,
        )
    ):
        result.append(
            Chunk(
                stable_hash(text),
                paper,
                text,
                5,
                0,
                5,
                0,
                len(text),
                (SourceSpan(index + 3, "Model", 0, len(text)),),
            )
        )
    return result


def test_persistence_search_and_complete_source_metadata(tmp_path, descriptor, chunks):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    index.upsert(chunks, [[1, 0, 0], [0, 1, 0]])
    index.finish({chunk.chunk_id for chunk in chunks})
    reopened = ChromaIndex(tmp_path, descriptor)
    hits = reopened.search([1, 0, 0], top_k=10)
    assert len(hits) == 2
    assert hits[0].text == chunks[0].text
    assert hits[0].score == pytest.approx(1)
    assert hits[0].paper_title == PAPERS[0].title
    assert hits[0].arxiv_id == "1706.03762"
    assert hits[0].version == 7
    assert hits[0].pages == (3,)
    assert hits[0].sections == ("Model",)
    assert "arXiv:1706.03762v7, p. 3" in hits[0].citation
    assert hits[0].source_url.endswith("1706.03762v7#page=3")
    assert hits[0].sources[0].end_char == len(hits[0].text)
    assert reopened.client.get_settings().anonymized_telemetry is False


def test_idempotent_upsert_and_paper_filter(tmp_path, descriptor, chunks):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    for _ in range(2):
        index.upsert(chunks, [[1, 0, 0], [0, 1, 0]])
    index.finish({chunk.chunk_id for chunk in chunks})
    assert index.collection.count() == 2
    hits = index.search([1, 0, 0], top_k=4, arxiv_id="2410.00037")
    assert [hit.arxiv_id for hit in hits] == ["2410.00037"]
    assert index.search([1, 0, 0], top_k=4, arxiv_id="2507.07955") == []


def test_configuration_isolation_and_missing_index(tmp_path, descriptor):
    with pytest.raises(IndexingError, match="does not exist"):
        ChromaIndex(tmp_path / "missing", descriptor)
    first = ChromaIndex(tmp_path, descriptor, create=True)
    other = {**descriptor, "chunking": {"size": 600}}
    second = ChromaIndex(tmp_path, other, create=True)
    assert first.name != second.name
    assert second.collection.count() == 0


def test_incomplete_and_damaged_indexes_cannot_be_queried(tmp_path, descriptor, chunks):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    index.upsert(chunks[:1], [[1, 0, 0]])
    with pytest.raises(IndexingError, match="incomplete"):
        index.search([1, 0, 0], top_k=1)
    with pytest.raises(IndexingError, match="stored IDs differ"):
        index.finish({chunk.chunk_id for chunk in chunks})
    index.finish({chunks[0].chunk_id})
    index.collection.delete(ids=[chunks[0].chunk_id])
    with pytest.raises(IndexingError, match="count changed"):
        index.search([1, 0, 0], top_k=1)


@pytest.mark.parametrize("vector", [[0, 0, 0], [1, 2], [float("nan"), 0, 1]])
def test_invalid_embeddings_are_rejected(tmp_path, descriptor, chunks, vector):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    with pytest.raises(IndexingError, match="Invalid embedding"):
        index.upsert(chunks[:1], [vector])
    index.upsert(chunks[:1], [[1, 0, 0]])
    index.finish({chunks[0].chunk_id})
    with pytest.raises(IndexingError, match="Invalid query embedding"):
        index.search(vector, top_k=1)


def test_collection_identity_is_verified(tmp_path, descriptor):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    index.collection.modify(metadata={**index.collection.metadata, "fingerprint": "invalid"})
    with pytest.raises(IndexingError, match="fingerprint"):
        ChromaIndex(tmp_path, descriptor)


def test_nonconsecutive_pages_are_not_fabricated(tmp_path, descriptor, chunks):
    chunk = replace(
        chunks[0],
        sources=(
            SourceSpan(2, "Introduction", 0, 10),
            SourceSpan(4, "Methods", 10, len(chunks[0].text)),
        ),
    )
    index = ChromaIndex(tmp_path, descriptor, create=True)
    index.upsert([chunk], [[1, 0, 0]])
    index.finish({chunk.chunk_id})
    hit = index.search([1, 0, 0], top_k=1)[0]
    assert hit.pages == (2, 4)
    assert "pp. 2, 4" in hit.citation


def test_query_limits_are_validated(tmp_path, descriptor):
    index = ChromaIndex(tmp_path, descriptor, create=True)
    for k in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="top_k"):
            index.search([1, 0, 0], top_k=k)
