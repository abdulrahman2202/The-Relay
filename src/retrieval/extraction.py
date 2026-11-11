"""Page-aware PyMuPDF extraction with conservative section recognition."""

import logging
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

import pymupdf

from .errors import ExtractionError
from .layout import PageLayout, TextLine, normalize, read_page
from .models import (
    ExtractedPaper,
    ExtractionIssue,
    PageText,
    PaperSpec,
    SectionSpan,
    TextRegion,
    content_hash,
)
from .text import dehyphenate

logger = logging.getLogger(__name__)
_SECTION_PREFIX = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})*\.?|[A-Z](?:\.\d{1,2})*)\s+")
_SECTION_NUMBER = re.compile(r"(?:\d{1,2}(?:\.\d{1,2})*|[A-Z](?:\.\d{1,2})*)")
_NAMED_HEADINGS = {"abstract", "references", "acknowledgments", "acknowledgements", "appendix"}


def _heading_key(text: str) -> str:
    return _SECTION_PREFIX.sub("", normalize(text)).casefold().rstrip(".")


def _page_lines(page: pymupdf.Page, title: str) -> PageLayout:
    return read_page(page, title)


def _assemble_page(
    lines: tuple[TextLine, ...],
    known_headings: set[str],
    current_section: str | None,
    *,
    has_outline: bool = False,
) -> tuple[str, tuple[SectionSpan, ...], str | None, tuple[TextRegion, ...]]:
    parts: list[str] = []
    sections: list[SectionSpan] = []
    position = 0
    section_start = 0
    regions = []
    body_size = median(line.size for line in lines) if lines else 0
    candidates: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for index, line in enumerate(lines):
        text = line.text
        if line.kind != "text" or "\n" in text:
            continue
        key = _heading_key(text)
        prefix = _SECTION_PREFIX.match(text)
        previous = lines[index - 1] if index else None
        split_number = bool(
            not prefix
            and previous
            and previous.kind == "text"
            and _SECTION_NUMBER.fullmatch(previous.text)
            and 0 <= line.bbox[0] - previous.bbox[0] < 100
            and -3 <= line.bbox[1] - previous.bbox[1] < 35
        )
        fallback = (
            not has_outline
            and prefix
            and (line.bold or line.size > body_size * 1.2)
            and len(text) <= 90
            and len(text.split()) <= 12
            and re.match(r"[A-Z][A-Za-z]", text[prefix.end() :])
            and not text.endswith((".", ",", ";", ":"))
        )
        if key in known_headings or key in _NAMED_HEADINGS or fallback:
            start = index - 1 if split_number else index
            label = f"{previous.text} {text}" if split_number else text
            candidates[key].append((int(bool(prefix or split_number)), start, label))
    headings = {}
    for matches in candidates.values():
        # A numbered heading takes precedence over a same-page figure label.
        _, start, label = max(matches, key=lambda item: (item[0], -item[1]))
        headings[start] = label
    index = 0
    while index < len(lines):
        line = lines[index]
        if index in headings and headings[index] != current_section:
            if position > section_start:
                sections.append(SectionSpan(section_start, position, current_section))
            current_section = headings[index]
            section_start = position
        group = [line]
        index += 1
        while (
            index < len(lines)
            and index not in headings
            and lines[index].block == line.block
            and lines[index].kind == line.kind
            and line.kind == "text"
        ):
            group.append(lines[index])
            index += 1
        text = dehyphenate("\n".join(item.text for item in group))
        bbox = (
            min(item.bbox[0] for item in group),
            min(item.bbox[1] for item in group),
            max(item.bbox[2] for item in group),
            max(item.bbox[3] for item in group),
        )
        regions.append(TextRegion(position, position + len(text), line.kind, bbox))
        parts.append(text + "\n\n")
        position += len(text) + 2
    if position > section_start:
        sections.append(SectionSpan(section_start, position, current_section))
    return "".join(parts), tuple(sections), current_section, tuple(regions)


def extract_pdf(paper: PaperSpec, papers_dir: Path) -> ExtractedPaper:
    """Extract all readable pages. Page failures are fatal; blank/duplicate pages are reported.

    Corpus validation is separate so extraction can also be tested with generated PDFs.
    Pages use physical, one-based PDF numbering, including front matter and appendices.
    """
    path = Path(papers_dir) / paper.filename
    pages: list[PageText] = []
    issues: list[ExtractionIssue] = []
    seen: dict[str, int] = {}
    current_section = None
    try:
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ExtractionError(f"Encrypted PDF requires a password: {path}")
            headings_by_page: dict[int, set[str]] = defaultdict(set)
            outline = document.get_toc()
            for _, title, heading_page in outline:
                headings_by_page[heading_page].add(_heading_key(title))
            page_count = document.page_count
            for page_index in range(page_count):
                page_number = page_index + 1
                try:
                    layout = _page_lines(document[page_index], paper.title)
                    issues.extend(layout.issues)
                    text, sections, next_section, regions = _assemble_page(
                        layout.lines,
                        headings_by_page[page_number],
                        current_section,
                        has_outline=bool(outline),
                    )
                except Exception as exc:
                    raise ExtractionError(
                        f"Extraction failed for {paper.filename}, page {page_number}: {exc}"
                    ) from exc
                if not text.strip():
                    issue = ExtractionIssue("empty_page", page_number, "No extractable body text")
                    issues.append(issue)
                    logger.warning("%s page %d: %s", paper.filename, page_number, issue.message)
                    continue
                digest = content_hash(text)
                duplicate_of = seen.get(digest)
                if duplicate_of is not None:
                    issue = ExtractionIssue(
                        "duplicate_page", page_number, "Repeated normalized page text", duplicate_of
                    )
                    issues.append(issue)
                    logger.warning(
                        "%s page %d duplicates page %d", paper.filename, page_number, duplicate_of
                    )
                else:
                    seen[digest] = page_number
                    current_section = next_section
                pages.append(PageText(page_number, text, sections, digest, duplicate_of, regions))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Cannot extract {path}: {exc}") from exc
    if not pages:
        raise ExtractionError(f"No extractable text in {path}; scanned PDFs require OCR")
    logger.info("Extracted %s: %d pages, %d issues", paper.filename, page_count, len(issues))
    return ExtractedPaper(paper, page_count, tuple(pages), tuple(issues))
