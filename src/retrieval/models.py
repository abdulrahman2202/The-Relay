"""Data passed between extraction, chunking, indexing, and retrieval."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """Ignore whitespace differences, but preserve case and mathematical symbols."""
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PaperSpec:
    title: str
    arxiv_id: str
    version: int
    filename: str
    sha256: str

    @property
    def document_id(self) -> str:
        return f"arxiv:{self.arxiv_id}v{self.version}:{self.sha256}"

    @property
    def url(self) -> str:
        return f"https://arxiv.org/pdf/{self.arxiv_id}v{self.version}"


@dataclass(frozen=True)
class ExtractionIssue:
    kind: str
    page_number: int
    message: str
    duplicate_of: int | None = None


@dataclass(frozen=True)
class SectionSpan:
    start_char: int
    end_char: int
    section: str | None


@dataclass(frozen=True)
class TextRegion:
    """A normalized text block with its physical PDF bounding box."""

    start_char: int
    end_char: int
    kind: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    sections: tuple[SectionSpan, ...]
    content_hash: str
    duplicate_of: int | None = None
    regions: tuple[TextRegion, ...] = ()


@dataclass(frozen=True)
class ExtractedPaper:
    paper: PaperSpec
    page_count: int
    pages: tuple[PageText, ...]
    issues: tuple[ExtractionIssue, ...]


@dataclass(frozen=True)
class SourceSpan:
    """Character offsets are relative to the returned chunk, not the PDF binary."""

    page_number: int
    section: str | None
    start_char: int
    end_char: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    paper: PaperSpec
    text: str
    token_count: int
    token_start: int
    token_end: int
    char_start: int
    char_end: int
    sources: tuple[SourceSpan, ...]

    @property
    def pages(self) -> tuple[int, ...]:
        return tuple(sorted({source.page_number for source in self.sources}))

    def metadata(self) -> dict[str, str | int]:
        sections = list(dict.fromkeys(s.section for s in self.sources if s.section))
        return {
            "document_id": self.paper.document_id,
            "paper_title": self.paper.title,
            "arxiv_id": self.paper.arxiv_id,
            "version": self.paper.version,
            "pdf_sha256": self.paper.sha256,
            "source_file": self.paper.filename,
            "source_url": self.paper.url,
            "page_number": self.pages[0],
            "page_start": self.pages[0],
            "page_end": self.pages[-1],
            "page_numbers_json": json.dumps(self.pages),
            "section": " | ".join(sections),
            "sections_json": json.dumps(sections, ensure_ascii=True),
            "source_spans_json": json.dumps([asdict(s) for s in self.sources], ensure_ascii=True),
            "token_count": self.token_count,
            "token_start": self.token_start,
            "token_end": self.token_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "content_sha256": content_hash(self.text),
        }


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    text: str
    paper_title: str
    arxiv_id: str
    version: int
    pages: tuple[int, ...]
    sections: tuple[str, ...]
    sources: tuple[SourceSpan, ...]
    distance: float | None
    retrieval_method: str = "vector"
    retrieval_score: float | None = None
    char_start: int | None = None
    parent_chunk_id: str | None = None

    @property
    def score(self) -> float:
        """Method-specific ranking score; never a factual-confidence estimate."""
        if self.retrieval_score is not None:
            return self.retrieval_score
        return 1.0 - self.distance if self.distance is not None else 0.0

    @property
    def citation(self) -> str:
        page_label = "p." if len(self.pages) == 1 else "pp."
        pages = ", ".join(str(page) for page in self.pages)
        return f"{self.paper_title} (arXiv:{self.arxiv_id}v{self.version}, {page_label} {pages})"

    @property
    def source_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.arxiv_id}v{self.version}#page={self.pages[0]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "score": self.score,
            "score_type": {"vector": "cosine_similarity", "bm25": "bm25", "hybrid": "rrf"}[
                self.retrieval_method
            ],
            "citation": self.citation,
            "source_url": self.source_url,
        }
