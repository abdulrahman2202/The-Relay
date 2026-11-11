import pytest

from retrieval.config import PRESETS
from retrieval.pipeline import RetrievalPipeline


@pytest.mark.integration
@pytest.mark.parametrize("size", [300, 600, 900])
def test_real_corpus_index_and_cited_retrieval(size, papers_dir, tmp_path, local_model):
    pipeline = RetrievalPipeline(
        papers_dir=papers_dir,
        db_dir=tmp_path / "chroma",
        config=PRESETS[size],
        embedder=local_model,
    )
    report = pipeline.ingest()
    assert len(report["documents"]) == 3
    assert sum(doc["page_count"] for doc in report["documents"]) == 120
    assert report["new_chunks"] == report["total_chunks"]
    cases = [
        (
            "Why does scaled dot-product attention divide by the square root of key dimension?",
            "1706.03762",
            {4},
        ),
        (
            "What are the theoretical and practical latency of Moshi full-duplex speech dialogue?",
            "2410.00037",
            {1, 2},
        ),
        (
            "How does H-Net replace tokenization using a learned dynamic chunking mechanism?",
            "2507.07955",
            # Figure 1 (p. 3), architecture (p. 4), and conclusion (p. 23) also
            # explain the learned replacement; verified against the supplied PDF.
            {1, 2, 3, 4, 6, 23},
        ),
    ]
    for query, arxiv_id, relevant_pages in cases:
        hits = pipeline.search(query)
        assert len(hits) == PRESETS[size].top_k
        assert any(
            hit.arxiv_id == arxiv_id and relevant_pages.intersection(hit.pages) for hit in hits
        ), [(hit.arxiv_id, hit.pages) for hit in hits]
        assert all(hit.text and hit.citation and hit.sources for hit in hits)
    latency_hits = pipeline.search(cases[1][0], strategy="bm25", top_k=3)
    assert any(
        hit.arxiv_id == "2410.00037"
        and hit.version == 1
        and 1 in hit.pages
        and "160ms" in hit.text
        and "200ms in practice" in hit.text
        for hit in latency_hits
    ), [(hit.pages, hit.text) for hit in latency_hits]
    assert pipeline.ingest()["new_chunks"] == 0
