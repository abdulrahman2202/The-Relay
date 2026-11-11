from dataclasses import replace

import pytest

from retrieval.config import RagConfig
from retrieval.errors import EmbeddingError, ExtractionError, IndexingError
from retrieval.index import ChromaIndex
from retrieval.models import PageText, SectionSpan, content_hash
from retrieval.pipeline import RetrievalPipeline, build_context


@pytest.fixture
def pipeline(tmp_path, small_documents, test_embedder, monkeypatch):
    instance = RetrievalPipeline(
        db_dir=tmp_path / "chroma",
        config=RagConfig(chunk_size=5, overlap=1, batch_size=2),
        embedder=test_embedder,
    )
    monkeypatch.setattr(instance, "extract", lambda: small_documents)
    return instance


def test_repeat_ingestion_skips_embeddings_and_top_k_does_not_reindex(pipeline, test_embedder):
    first = pipeline.ingest()
    calls = test_embedder.calls
    second = pipeline.ingest()
    assert first["total_chunks"] > 3
    assert second["new_chunks"] == 0
    assert second["reused_chunks"] == first["total_chunks"]
    assert test_embedder.calls == calls
    pipeline.config = replace(pipeline.config, top_k=5)
    assert pipeline.ingest()["fingerprint"] == first["fingerprint"]
    assert len(pipeline.search("attention")) == 5


def test_interrupted_ingestion_is_hidden_and_resumes(pipeline, test_embedder):
    test_embedder.fail_on_call = 2
    with pytest.raises(EmbeddingError, match="interruption"):
        pipeline.ingest()
    index = ChromaIndex(pipeline.db_dir, pipeline.descriptor)
    saved = index.ids()
    assert len(saved) == 2
    with pytest.raises(IndexingError, match="incomplete"):
        pipeline.search("speech")
    assert test_embedder.calls == 2
    test_embedder.fail_on_call = None
    report = pipeline.ingest()
    assert report["reused_chunks"] == len(saved)
    assert report["new_chunks"] == report["total_chunks"] - len(saved)
    assert pipeline.search("speech moshi")[0].arxiv_id == "2410.00037"


def test_extraction_failure_never_creates_an_index(pipeline, test_embedder, monkeypatch):
    def fail():
        raise ExtractionError("Failed page")

    monkeypatch.setattr(pipeline, "extract", fail)
    with pytest.raises(ExtractionError, match="Failed page"):
        pipeline.ingest()
    assert not pipeline.db_dir.exists()
    assert test_embedder.calls == 0


def test_duplicate_chunks_are_reported(pipeline, small_documents, monkeypatch):
    text = "alpha beta alpha beta alpha beta"
    page = PageText(1, text, (SectionSpan(0, len(text), "Abstract"),), content_hash(text))
    document = replace(small_documents[0], pages=(page,))
    monkeypatch.setattr(pipeline, "extract", lambda: [document, *small_documents[1:]])
    pipeline.config = RagConfig(chunk_size=2, overlap=0)
    report = pipeline.ingest()
    assert len(report["duplicate_chunks"]) == 2
    assert report["documents"][0]["chunks"] == 1
    assert all(not duplicate["indexed"] for duplicate in report["duplicate_chunks"])


def test_changed_configuration_uses_another_collection(pipeline):
    first = pipeline.ingest()
    pipeline.config = replace(pipeline.config, overlap=2)
    second = pipeline.ingest()
    assert first["collection"] != second["collection"]
    assert second["reused_chunks"] == 0


def test_cross_paper_duplicates_preserve_both_citations(pipeline, small_documents, monkeypatch):
    second = replace(small_documents[1], pages=small_documents[0].pages)
    monkeypatch.setattr(
        pipeline, "extract", lambda: [small_documents[0], second, small_documents[2]]
    )
    pipeline.config = RagConfig(chunk_size=100, overlap=0)
    report = pipeline.ingest()
    assert report["total_chunks"] == 3
    assert len(report["duplicate_chunks"]) == 1
    assert report["duplicate_chunks"][0]["kind"] == "cross_paper_duplicate"
    assert report["duplicate_chunks"][0]["indexed"] is True
    assert len({hit.arxiv_id for hit in pipeline.search("attention transformer")}) == 3


def test_filter_and_query_validation(pipeline):
    for query in ("", " ", None):
        with pytest.raises(ValueError, match="query"):
            pipeline.search(query)
    with pytest.raises(ValueError, match="top_k"):
        pipeline.search("attention", top_k=0)
    with pytest.raises(ValueError, match="three supplied"):
        pipeline.search("attention", arxiv_id="1234.56789")
    pipeline.ingest()
    hits = pipeline.search("attention", arxiv_id="2410.00037", top_k=99)
    assert hits
    assert all(hit.arxiv_id == "2410.00037" for hit in hits)


def test_context_budget_includes_citations(pipeline, tokenizer):
    pipeline.ingest()
    hits = pipeline.search("speech moshi")
    full = build_context(hits, tokenizer, max_tokens=1000)
    assert hits[0].citation in full
    first_only = build_context(hits[:1], tokenizer, max_tokens=1000)
    budget = len(tokenizer.encode(first_only))
    bounded = build_context(hits, tokenizer, max_tokens=budget)
    assert bounded == first_only
    assert len(tokenizer.encode(bounded)) <= budget
    assert build_context(hits, tokenizer, max_tokens=1) == ""
    with pytest.raises(ValueError, match="max_tokens"):
        build_context(hits, tokenizer, max_tokens=0)


def test_deleted_rows_are_repaired_on_retry(pipeline):
    report = pipeline.ingest()
    index = ChromaIndex(pipeline.db_dir, pipeline.descriptor)
    index.collection.delete(ids=[next(iter(index.ids()))])
    repaired = pipeline.ingest()
    assert repaired["new_chunks"] == 1
    assert repaired["total_chunks"] == report["total_chunks"]
    assert pipeline.search("chunking")


def test_lexical_and_hybrid_search_share_the_index_and_preserve_filters(pipeline, test_embedder):
    original = pipeline.ingest()
    calls = test_embedder.calls
    hits = pipeline.search("speech moshi", strategy="bm25", arxiv_id="2410.00037")
    assert hits and all(hit.arxiv_id == "2410.00037" for hit in hits)
    assert test_embedder.calls == calls
    pipeline.config = replace(pipeline.config, strategy="hybrid", rrf_constant=40)
    assert pipeline.ingest()["fingerprint"] == original["fingerprint"]
    results = pipeline.search("speech moshi", arxiv_id="2410.00037")
    assert results and all(hit.retrieval_method == "hybrid" for hit in results)
    assert all(hit.arxiv_id == "2410.00037" for hit in results)


def test_extraction_cache_still_validates_pdf_bytes(small_documents, monkeypatch):
    calls = []

    def extract(paper, path):
        calls.append(paper.arxiv_id)
        return next(doc for doc in small_documents if doc.paper == paper)

    monkeypatch.setattr(
        "retrieval.pipeline.validate_corpus", lambda path: [d.paper for d in small_documents]
    )
    monkeypatch.setattr("retrieval.pipeline.extract_pdf", extract)
    pipeline = RetrievalPipeline()
    assert pipeline.extract() == pipeline.extract()
    assert len(calls) == 3

    def changed(path):
        raise ExtractionError("PDF bytes changed")

    monkeypatch.setattr("retrieval.pipeline.validate_corpus", changed)
    with pytest.raises(ExtractionError, match="PDF bytes changed"):
        pipeline.extract()
