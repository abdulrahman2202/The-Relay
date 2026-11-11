"""Persistent Chroma storage; embedding functions and telemetry are disabled."""

import json
import logging
from pathlib import Path
from typing import Any

import chromadb
import numpy as np
from chromadb.config import Settings

from .errors import IndexingError
from .models import Chunk, SearchHit, SourceSpan, stable_hash

logger = logging.getLogger(__name__)


def _hit(chunk_id: str, text: str, metadata: dict[str, Any], distance: float | None) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        text=text,
        paper_title=metadata["paper_title"],
        arxiv_id=metadata["arxiv_id"],
        version=metadata["version"],
        pages=tuple(json.loads(metadata["page_numbers_json"])),
        sections=tuple(json.loads(metadata["sections_json"])),
        sources=tuple(SourceSpan(**span) for span in json.loads(metadata["source_spans_json"])),
        distance=distance,
        char_start=metadata["char_start"],
    )


class ChromaIndex:
    def __init__(self, path: Path, descriptor: dict[str, Any], *, create: bool = False) -> None:
        self.fingerprint = stable_hash(descriptor)
        self.name = f"relay_{self.fingerprint[:32]}"
        self.dimension = descriptor["embedding"]["dimension"]
        try:
            if not create and not (Path(path) / "chroma.sqlite3").is_file():
                raise IndexingError("Index does not exist; run ingestion for this configuration")
            self.client = chromadb.PersistentClient(
                path=str(path), settings=Settings(anonymized_telemetry=False)
            )
            if create:
                self.collection = self.client.get_or_create_collection(
                    name=self.name,
                    embedding_function=None,
                    configuration={
                        "hnsw": {
                            "space": "cosine",
                            "ef_construction": 200,
                            "ef_search": 100,
                            "num_threads": 1,
                        }
                    },
                    metadata={
                        "fingerprint": self.fingerprint,
                        "descriptor_json": json.dumps(descriptor, sort_keys=True),
                        "ready": False,
                        "expected_count": 0,
                    },
                )
            else:
                self.collection = self.client.get_collection(
                    name=self.name, embedding_function=None
                )
            if (self.collection.metadata or {}).get("fingerprint") != self.fingerprint:
                raise IndexingError("Collection fingerprint does not match this pipeline")
        except IndexingError:
            raise
        except Exception as exc:
            raise IndexingError(
                f"Cannot open Chroma collection {self.name}: {exc}. "
                "Run ingestion with matching chunk and model settings."
            ) from exc

    def ids(self) -> set[str]:
        try:
            return set(self.collection.get(include=[])["ids"])
        except Exception as exc:
            raise IndexingError(f"Cannot inspect index: {exc}") from exc

    def mark_pending(self) -> None:
        try:
            self.collection.modify(metadata={**self.collection.metadata, "ready": False})
        except Exception as exc:
            raise IndexingError(f"Cannot mark index incomplete: {exc}") from exc

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        vectors = np.asarray(embeddings, dtype=np.float32)
        if (
            vectors.shape != (len(chunks), self.dimension)
            or not np.isfinite(vectors).all()
            or np.any(np.linalg.norm(vectors, axis=1) <= 0)
        ):
            raise IndexingError("Invalid embedding count, dimension, or values")
        try:
            self.collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=vectors,
                documents=[chunk.text for chunk in chunks],
                metadatas=[chunk.metadata() for chunk in chunks],
            )
        except Exception as exc:
            raise IndexingError(f"Cannot store embedding batch: {exc}") from exc

    def finish(self, expected_ids: set[str]) -> None:
        if not expected_ids or self.ids() != expected_ids:
            raise IndexingError("Index verification failed: stored IDs differ from expected chunks")
        try:
            self.collection.modify(
                metadata={
                    **self.collection.metadata,
                    "ready": True,
                    "expected_count": len(expected_ids),
                    "ids_sha256": stable_hash(sorted(expected_ids)),
                }
            )
        except Exception as exc:
            raise IndexingError(f"Cannot finalize index: {exc}") from exc
        logger.info("Index %s ready: %d chunks", self.name, len(expected_ids))

    def ensure_ready(self) -> None:
        try:
            metadata = self.collection.metadata or {}
            if not metadata.get("ready"):
                raise IndexingError("Index is incomplete; rerun ingestion to finish it")
            if self.collection.count() != metadata.get("expected_count"):
                raise IndexingError("Index count changed; rerun ingestion to verify or repair it")
        except IndexingError:
            raise
        except Exception as exc:
            raise IndexingError(f"Cannot check index state: {exc}") from exc

    def search(
        self, vector: list[float], *, top_k: int, arxiv_id: str | None = None
    ) -> list[SearchHit]:
        if type(top_k) is not int or top_k < 1:
            raise ValueError("top_k must be a positive integer")
        self.ensure_ready()
        query = np.asarray(vector, dtype=np.float32)
        if (
            query.shape != (self.dimension,)
            or not np.isfinite(query).all()
            or np.linalg.norm(query) <= 0
        ):
            raise IndexingError("Invalid query embedding")
        where = {"arxiv_id": arxiv_id} if arxiv_id else None
        try:
            available = len(self.collection.get(where=where, include=[])["ids"])
            if not available:
                return []
            result = self.collection.query(
                query_embeddings=[vector],
                n_results=min(top_k, available),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            hits = []
            for chunk_id, text, metadata, distance in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            ):
                hits.append(_hit(chunk_id, text, metadata, float(distance)))
            # Stable ordering for equal distances within the returned candidate set.
            return sorted(hits, key=lambda hit: (hit.distance, hit.chunk_id))
        except Exception as exc:
            raise IndexingError(f"Semantic search failed: {exc}") from exc

    def documents(self, *, arxiv_id: str | None = None) -> list[SearchHit]:
        """Read the same ready collection for lexical retrieval; no second store."""
        self.ensure_ready()
        try:
            result = self.collection.get(
                where={"arxiv_id": arxiv_id} if arxiv_id else None,
                include=["documents", "metadatas"],
            )
            return sorted(
                (
                    _hit(identifier, text, meta, None)
                    for identifier, text, meta in zip(
                        result["ids"], result["documents"], result["metadatas"], strict=True
                    )
                ),
                key=lambda hit: hit.chunk_id,
            )
        except Exception as exc:
            raise IndexingError(f"Cannot read lexical search documents: {exc}") from exc
