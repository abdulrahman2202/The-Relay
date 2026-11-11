"""Orchestration for the fixed corpus; no LLM or remote inference client is used."""

import logging
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .catalog import PAPERS, validate_corpus
from .chunking import chunk_paper
from .config import PIPELINE_VERSION, RagConfig
from .context import build_context, select_context
from .embeddings import Embedder, LocalEmbedder
from .errors import IndexingError
from .evidence import EvidenceRequirement, assess_evidence, infer_requirements
from .extraction import extract_pdf
from .index import ChromaIndex
from .lexical import BM25, reciprocal_rank_fusion
from .models import Chunk, ExtractedPaper, SearchHit, content_hash

logger = logging.getLogger(__name__)


def runtime_versions() -> dict[str, str]:
    return {
        name: version(name)
        for name in (
            "pymupdf",
            "sentence-transformers",
            "chromadb",
            "numpy",
            "torch",
            "transformers",
            "tokenizers",
            "huggingface-hub",
        )
    }


def extraction_summary(document: ExtractedPaper) -> dict[str, Any]:
    return {
        **asdict(document.paper),
        "document_id": document.paper.document_id,
        "page_count": document.page_count,
        "extracted_pages": len(document.pages),
        "unique_pages": sum(page.duplicate_of is None for page in document.pages),
        "issues": [asdict(issue) for issue in document.issues],
    }


class RetrievalPipeline:
    def __init__(
        self,
        *,
        papers_dir: Path = Path("papers"),
        db_dir: Path = Path("data/chroma-v2"),
        config: RagConfig | None = None,
        model_cache: Path | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.papers_dir = Path(papers_dir)
        self.db_dir = Path(db_dir)
        self.config = config if config is not None else RagConfig()
        self.model_cache = model_cache
        self._embedder = embedder
        self._extracted: tuple[ExtractedPaper, ...] | None = None

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = LocalEmbedder(
                batch_size=self.config.batch_size, cache_dir=self.model_cache
            )
        return self._embedder

    @property
    def descriptor(self) -> dict[str, Any]:
        return {
            "pipeline": PIPELINE_VERSION,
            "corpus": [asdict(paper) for paper in PAPERS],
            "chunking": self.config.indexing_settings,
            "embedding": self.embedder.descriptor,
            "runtime": runtime_versions(),
        }

    def extract(self) -> list[ExtractedPaper]:
        papers = validate_corpus(self.papers_dir)
        # Recheck the exact PDF bytes on every call. Immutable extraction results
        # may then be reused within this instance, including ingestion retries.
        if self._extracted is None:
            self._extracted = tuple(extract_pdf(paper, self.papers_dir) for paper in papers)
        return list(self._extracted)

    def ingest(self) -> dict[str, Any]:
        # Complete validation/extraction/chunking before mutating the persistent store.
        documents = self.extract()
        chunks: list[Chunk] = []
        duplicates: list[dict[str, Any]] = []
        seen: dict[tuple[str, str], Chunk] = {}
        across_papers: dict[str, Chunk] = {}
        for document in documents:
            paper_chunks = chunk_paper(document, self.embedder.tokenizer, self.config)
            if not paper_chunks:
                raise IndexingError(f"No usable chunks for {document.paper.filename}")
            for chunk in paper_chunks:
                digest = content_hash(chunk.text)
                key = (chunk.paper.document_id, digest)
                original = seen.get(key)
                if original is not None:
                    duplicates.append(
                        {
                            "kind": "duplicate_chunk",
                            "chunk_id": chunk.chunk_id,
                            "kept_chunk_id": original.chunk_id,
                            "arxiv_id": chunk.paper.arxiv_id,
                            "pages": chunk.pages,
                            "indexed": False,
                        }
                    )
                    logger.warning("Skipping duplicate chunk %s", chunk.chunk_id)
                    continue
                other = across_papers.get(digest)
                if other is not None and other.paper.document_id != chunk.paper.document_id:
                    # Preserve both papers' attribution even when they quote the same text.
                    duplicates.append(
                        {
                            "kind": "cross_paper_duplicate",
                            "chunk_id": chunk.chunk_id,
                            "other_chunk_id": other.chunk_id,
                            "indexed": True,
                        }
                    )
                    logger.warning("Identical text occurs in multiple papers: %s", chunk.chunk_id)
                seen[key] = chunk
                across_papers.setdefault(digest, chunk)
                chunks.append(chunk)
        descriptor = self.descriptor
        index = ChromaIndex(self.db_dir, descriptor, create=True)
        expected = {chunk.chunk_id for chunk in chunks}
        existing = index.ids()
        if existing - expected:
            raise IndexingError(
                "Collection contains unexpected IDs; use a fresh database directory"
            )
        missing = [chunk for chunk in chunks if chunk.chunk_id not in existing]
        index.mark_pending()
        batch_size = min(self.config.batch_size, index.client.get_max_batch_size())
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            vectors = self.embedder.embed([chunk.text for chunk in batch])
            index.upsert(batch, vectors)
            logger.info(
                "Indexed %d/%d new chunks", min(start + batch_size, len(missing)), len(missing)
            )
        index.finish(expected)
        counts = Counter(chunk.paper.arxiv_id for chunk in chunks)
        return {
            "collection": index.name,
            "fingerprint": index.fingerprint,
            "configuration": asdict(self.config),
            "descriptor": descriptor,
            "total_chunks": len(chunks),
            "new_chunks": len(missing),
            "reused_chunks": len(existing),
            "documents": [
                {**extraction_summary(doc), "chunks": counts[doc.paper.arxiv_id]}
                for doc in documents
            ],
            "duplicate_chunks": duplicates,
        }

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        arxiv_id: str | None = None,
        strategy: str | None = None,
    ) -> list[SearchHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a nonempty string")
        k = self.config.top_k if top_k is None else top_k
        if type(k) is not int or k < 1:
            raise ValueError("top_k must be a positive integer")
        if arxiv_id is not None and arxiv_id not in {paper.arxiv_id for paper in PAPERS}:
            raise ValueError("arxiv_id must identify one of the three supplied papers")
        method = self.config.strategy if strategy is None else strategy
        if method not in {"vector", "bm25", "hybrid"}:
            raise ValueError("strategy must be vector, bm25, or hybrid")
        index = ChromaIndex(self.db_dir, self.descriptor)
        index.ensure_ready()
        count = max(k, self.config.candidate_k) if method == "hybrid" else k
        dense = []
        if method != "bm25":
            vector = self.embedder.embed([query])[0]
            dense = index.search(vector, top_k=count, arxiv_id=arxiv_id)
        if method == "vector":
            return dense
        lexical = BM25(
            index.documents(arxiv_id=arxiv_id), k1=self.config.bm25_k1, b=self.config.bm25_b
        ).search(query, top_k=count)
        if method == "bm25":
            return lexical
        return reciprocal_rank_fusion(dense, lexical, top_k=k, constant=self.config.rrf_constant)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        arxiv_id: str | None = None,
        strategy: str | None = None,
        max_tokens: int = 4096,
        requirements: tuple[EvidenceRequirement, ...] = (),
    ) -> dict[str, Any]:
        """Retrieve and assess bounded evidence, without generating an answer."""
        if type(max_tokens) is not int or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        hits = self.search(query, top_k=top_k, arxiv_id=arxiv_id, strategy=strategy)
        context = select_context(hits, self.embedder.tokenizer, max_tokens=max_tokens, query=query)
        checks = infer_requirements(query, arxiv_id=arxiv_id) + requirements
        assessment = assess_evidence(context.hits, checks)
        return {
            "query": query,
            "hits": [hit.to_dict() for hit in hits],
            "context": context.text,
            "context_tokens": context.token_count,
            "context_hits": [hit.to_dict() for hit in context.hits],
            "omitted_ids": list(context.omitted_ids),
            "evidence": {**asdict(assessment), "refused": assessment.refused},
            "requirements": [asdict(requirement) for requirement in checks],
        }


# Preserve the original public import path for clients.
__all__ = ["RetrievalPipeline", "build_context", "extraction_summary", "runtime_versions"]
