"""The only corpus accepted by the production ingestion pipeline."""

import hashlib
import logging
import re
from pathlib import Path

import pymupdf

from .errors import CorpusValidationError
from .models import PaperSpec

logger = logging.getLogger(__name__)

PAPERS = (
    PaperSpec(
        title="Attention Is All You Need",
        arxiv_id="1706.03762",
        version=7,
        filename="attention_is_all_you_need.pdf",
        sha256="bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697",
    ),
    PaperSpec(
        title="Moshi: a speech-text foundation model for real-time dialogue",
        arxiv_id="2410.00037",
        version=1,
        filename="moshi.pdf",
        sha256="a687144cc77bea86b0c60ae800ccb1d3e0816033fa5c7960388fe29a0dbfcfac",
    ),
    PaperSpec(
        title="Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        arxiv_id="2507.07955",
        version=2,
        filename="dynamic_chunking.pdf",
        sha256="04a2b32e6e82853cfc23c5db132750874a86cde99219ec6f664128f4aa83122f",
    ),
)


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_corpus(papers_dir: Path) -> tuple[PaperSpec, ...]:
    """Fail before any writes if files differ from the supplied corpus."""
    papers_dir = Path(papers_dir)
    if not papers_dir.is_dir():
        raise CorpusValidationError(f"Papers directory does not exist: {papers_dir}")
    actual = {p.name for p in papers_dir.iterdir() if p.suffix.lower() == ".pdf"}
    expected = {paper.filename for paper in PAPERS}
    if actual != expected:
        raise CorpusValidationError(
            f"Expected exactly the three supplied PDFs; missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}"
        )
    hashes: set[str] = set()
    for paper in PAPERS:
        path = papers_dir / paper.filename
        try:
            digest = file_sha256(path)
            if digest in hashes:
                raise CorpusValidationError(f"Duplicate PDF content: {paper.filename}")
            hashes.add(digest)
            if digest != paper.sha256:
                raise CorpusValidationError(
                    f"SHA-256 mismatch for {paper.filename}; use the supplied "
                    f"arXiv:{paper.arxiv_id}v{paper.version} PDF"
                )
            with pymupdf.open(path) as document:
                if document.needs_pass or not document.page_count:
                    raise CorpusValidationError(f"Unreadable PDF: {paper.filename}")
                text = document[0].get_text("text")
            identities = re.findall(r"arXiv:\s*(\d{4}\.\d{4,5})v(\d+)", text)
            if (paper.arxiv_id, str(paper.version)) not in identities:
                raise CorpusValidationError(
                    f"Missing or incorrect arXiv version stamp in {paper.filename}"
                )
        except CorpusValidationError:
            raise
        except Exception as exc:
            raise CorpusValidationError(f"Cannot validate {path}: {exc}") from exc
        logger.info("Validated arXiv:%sv%d (%s)", paper.arxiv_id, paper.version, digest)
    return PAPERS
