from dataclasses import replace

import pytest

from retrieval.lexical import BM25, reciprocal_rank_fusion
from retrieval.models import SearchHit, SourceSpan


def hit(identifier, text):
    return SearchHit(
        identifier,
        text,
        "Moshi",
        "2410.00037",
        1,
        (1,),
        ("Abstract",),
        (SourceSpan(1, "Abstract", 0, len(text)),),
        0.2,
    )


def test_bm25_recovers_hyphenated_numerical_evidence_with_citations():
    documents = [
        hit("background", "Moshi is a full-duplex speech dialogue system."),
        hit("evidence", "Moshi has a theoret-\nical latency of 160ms, 200ms in practice."),
    ]
    results = BM25(documents).search("Moshi theoretical latency 160 ms", top_k=2)
    assert results[0].chunk_id == "evidence"
    assert results[0].distance is None
    assert results[0].to_dict()["score_type"] == "bm25"
    assert results[0].sources == documents[1].sources
    assert "arXiv:2410.00037v1" in results[0].citation


def test_bm25_does_not_return_zero_score_neighbors():
    assert BM25([hit("one", "speech dialogue")]).search("quasars", top_k=3) == []
    assert BM25([]).search("speech", top_k=3) == []


def test_fusion_includes_lexical_only_evidence_and_deduplicates():
    first, second = hit("a", "topic"), hit("b", "measurement")
    lexical = replace(second, distance=None, retrieval_method="bm25", retrieval_score=5.0)
    results = reciprocal_rank_fusion([first, first], [lexical, first], top_k=5)
    assert [result.chunk_id for result in results] == ["a", "b"]
    assert results[1].distance is None
    assert all(result.to_dict()["score_type"] == "rrf" for result in results)
    assert len({result.chunk_id for result in results}) == len(results)


@pytest.mark.parametrize("settings", [{"k1": 0}, {"b": 2}, {"k1": float("nan")}])
def test_invalid_bm25_settings(settings):
    with pytest.raises(ValueError):
        BM25([], **settings)


def test_ties_have_deterministic_order():
    documents = [hit("b", "speech"), hit("a", "speech")]
    assert [h.chunk_id for h in BM25(documents).search("speech", top_k=2)] == ["a", "b"]
