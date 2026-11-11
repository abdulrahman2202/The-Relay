"""Immutable settings; query-only settings do not change the index identity."""

import math
from dataclasses import dataclass
from types import MappingProxyType

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
PIPELINE_VERSION = "relay-rag-v2.1"


@dataclass(frozen=True)
class RagConfig:
    chunk_size: int = 300
    overlap: int = 50
    top_k: int = 3
    batch_size: int = 16
    chunking: str = "boundary"
    strategy: str = "vector"
    candidate_k: int = 50
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    rrf_constant: int = 60

    def __post_init__(self) -> None:
        for name in ("chunk_size", "top_k", "batch_size", "candidate_k", "rrf_constant"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.overlap) is not int or not 0 <= self.overlap < self.chunk_size:
            raise ValueError("overlap must be an integer in [0, chunk_size)")
        if self.chunking not in {"boundary", "fixed"}:
            raise ValueError("chunking must be boundary or fixed")
        if self.strategy not in {"vector", "bm25", "hybrid"}:
            raise ValueError("strategy must be vector, bm25, or hybrid")
        for name, low, high in (("bm25_k1", 0, math.inf), ("bm25_b", 0, 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite number")
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} is outside its allowed range")
        if self.bm25_k1 == 0:
            raise ValueError("bm25_k1 must be positive")

    @property
    def indexing_settings(self) -> dict[str, int | str]:
        return {"chunk_size": self.chunk_size, "overlap": self.overlap, "chunking": self.chunking}


# A constant overlap keeps this variable fixed across the requested comparisons.
PRESETS = MappingProxyType(
    {
        300: RagConfig(chunk_size=300, overlap=50, top_k=3),
        600: RagConfig(chunk_size=600, overlap=50, top_k=4),
        900: RagConfig(chunk_size=900, overlap=50, top_k=5),
    }
)
