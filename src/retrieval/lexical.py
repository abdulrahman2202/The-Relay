"""Local BM25 and rank fusion over the same cited Chroma documents."""

import math
from collections import Counter
from dataclasses import replace

from .models import SearchHit
from .text import lexical_tokens


class BM25:
    def __init__(self, documents: list[SearchHit], *, k1: float = 1.5, b: float = 0.75) -> None:
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("BM25 requires k1 > 0 and 0 <= b <= 1")
        self.documents = documents
        self.k1, self.b = k1, b
        self.counts = [Counter(lexical_tokens(hit.text)) for hit in documents]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average = sum(self.lengths) / len(documents) if documents else 0
        self.frequencies = Counter(term for count in self.counts for term in count)

    def search(self, query: str, *, top_k: int) -> list[SearchHit]:
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        if not self.average:
            return []
        terms = set(lexical_tokens(query))
        results = []
        n = len(self.documents)
        for hit, counts, length in zip(self.documents, self.counts, self.lengths, strict=True):
            score = 0.0
            for term in sorted(terms):
                frequency = counts[term]
                if not frequency:
                    continue
                df = self.frequencies[term]
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (1 - self.b + self.b * length / self.average)
                score += idf * frequency * (self.k1 + 1) / denominator
            if score > 0:
                results.append(
                    replace(hit, distance=None, retrieval_method="bm25", retrieval_score=score)
                )
        return sorted(results, key=lambda hit: (-hit.score, hit.chunk_id))[:top_k]


def reciprocal_rank_fusion(
    vector: list[SearchHit], lexical: list[SearchHit], *, top_k: int, constant: int = 60
) -> list[SearchHit]:
    if type(constant) is not int or constant < 1 or type(top_k) is not int or top_k < 1:
        raise ValueError("RRF constant and top_k must be positive integers")
    scores: Counter[str] = Counter()
    documents = {}
    for ranking in (vector, lexical):
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            documents.setdefault(hit.chunk_id, hit)
            scores[hit.chunk_id] += 1 / (constant + rank)
    return [
        replace(documents[identifier], retrieval_method="hybrid", retrieval_score=score)
        for identifier, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[
            :top_k
        ]
    ]
