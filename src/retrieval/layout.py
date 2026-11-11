"""PDF geometry and text normalization, without interpreting scientific results."""

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from statistics import median
from typing import Any

import pymupdf

from .models import ExtractionIssue

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextLine:
    text: str
    bold: bool
    size: float
    bbox: tuple[float, float, float, float]
    baseline: float
    block: int
    kind: str = "text"


@dataclass(frozen=True)
class PageLayout:
    lines: tuple[TextLine, ...]
    issues: tuple[ExtractionIssue, ...]


def normalize(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _span_text(spans: list[dict[str, Any]]) -> str:
    fragments = []
    for index, span in enumerate(spans):
        value = span["text"]
        # Keep superscript meaning before NFKC erases typographical distinctions.
        if span["flags"] & 1 and value.strip():
            value = "^{" + value.strip() + "}"
        elif index and span["bbox"][0] - spans[index - 1]["bbox"][2] > 1:
            fragments.append(" ")
        fragments.append(value)
    return normalize("".join(fragments).replace("}^{", ""))


def _bounds(lines: list[TextLine]) -> tuple[float, float, float, float]:
    return (
        min(line.bbox[0] for line in lines),
        min(line.bbox[1] for line in lines),
        max(line.bbox[2] for line in lines),
        max(line.bbox[3] for line in lines),
    )


def _table_text(lines: list[TextLine]) -> tuple[str, bool]:
    """Use detected geometry, but original spans, to keep decimal points intact.

    Rows contain explicit separators. Missing cells remain empty when a modal
    row supplies unambiguous column positions. Spanning/multi-line headers remain
    separate rows; no numeric cell is inferred or filled from a neighboring row.
    """
    rows: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda line: (line.baseline, line.bbox[0])):
        if rows and abs(line.baseline - median(item.baseline for item in rows[-1])) <= 2.5:
            rows[-1].append(line)
        else:
            rows.append([line])
    for row in rows:
        row.sort(key=lambda line: line.bbox[0])
    counts = Counter(len(row) for row in rows if len(row) > 1)
    width = max(counts) if counts else 1
    regular = [row for row in rows if len(row) == width]
    centers = (
        [median((row[i].bbox[0] + row[i].bbox[2]) / 2 for row in regular) for i in range(width)]
        if regular
        else []
    )
    rendered = []
    ambiguous = False
    for row in rows:
        cells = [""] * width
        assigned = set()
        for line in row:
            center = (line.bbox[0] + line.bbox[2]) / 2
            column = min(range(width), key=lambda i: abs(center - centers[i])) if centers else 0
            nearest_gap = min(
                (abs(centers[column] - other) for i, other in enumerate(centers) if i != column),
                default=float("inf"),
            )
            if column in assigned or abs(center - centers[column]) > nearest_gap * 0.3:
                # A spanning header has no trustworthy one-to-one column mapping.
                cells = [item.text for item in row]
                ambiguous = True
                break
            assigned.add(column)
            cells[column] = line.text
        rendered.append(" | ".join(cells))
    return "\n".join(rendered), ambiguous


def read_page(page: pymupdf.Page, title: str) -> PageLayout:
    lines = []
    issues = []
    math_warning = False
    for block_number, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = line["spans"]
            raw = "".join(span["text"] for span in spans)
            if re.search(r"[\x00-\x08\x0b-\x1f]", raw) or any(ch in raw for ch in "√∑∫"):
                math_warning = True
            text = _span_text(spans)
            if not text:
                continue
            bbox = tuple(line["bbox"])
            dx, dy = line.get("dir", (1, 0))
            rotated = abs(dy) > abs(dx)
            if rotated and bbox[0] < page.rect.width * 0.08 and re.match(r"arXiv:\d", text):
                continue
            if text == str(page.number + 1) and bbox[1] > page.rect.height * 0.92:
                continue
            if bbox[1] < page.rect.height * 0.09 and text.casefold() == title.casefold():
                continue
            weights = [len(span["text"].strip()) for span in spans]
            total = sum(weights) or 1
            bold = sum(w for w, span in zip(weights, spans, strict=True) if span["flags"] & 16)
            sizes = [span["size"] for span in spans if not span["flags"] & 1]
            origins = [span["origin"][1] for span in spans if not span["flags"] & 1]
            lines.append(
                TextLine(
                    text,
                    bold / total >= 0.8,
                    median(sizes or [0]),
                    bbox,
                    median(origins or [bbox[3]]),
                    block_number,
                    "figure" if rotated else "text",
                )
            )
    # Use table detection for regions only. Its cell strings can reorder decimal
    # points and superscripts, so they must never replace the original PDF spans.
    try:
        boxes = [tuple(table.bbox) for table in page.find_tables().tables] if lines else []
    except Exception as exc:
        boxes = []
        issues.append(
            ExtractionIssue(
                "table_detection_failed",
                page.number + 1,
                f"Retained original text; table geometry unavailable: {exc}",
            )
        )
    used = set()
    replacements = {}
    table_warning = False
    for box in boxes:
        selected = []
        for index, line in enumerate(lines):
            cx = (line.bbox[0] + line.bbox[2]) / 2
            cy = (line.bbox[1] + line.bbox[3]) / 2
            if (
                index not in used
                and line.kind == "text"
                and box[0] - 3 <= cx <= box[2] + 3
                and box[1] - 3 <= cy <= box[3] + 3
            ):
                selected.append(index)
        if len(selected) < 4:
            continue
        members = [lines[index] for index in selected]
        used.update(selected)
        table_text, ambiguous = _table_text(members)
        table_warning |= ambiguous
        replacements[min(selected)] = replace(
            members[0], text=table_text, bbox=_bounds(members), bold=False, kind="table"
        )
    result = []
    for index, line in enumerate(lines):
        if index in replacements:
            result.append(replacements[index])
        elif index not in used:
            result.append(line)
    if math_warning:
        issues.append(
            ExtractionIssue(
                "math_layout_warning",
                page.number + 1,
                "Math glyphs retained as text; inspect the PDF for fractions "
                "and two-dimensional equations.",
            )
        )
    if table_warning:
        issues.append(
            ExtractionIssue(
                "table_layout_warning",
                page.number + 1,
                "Table rows retained; spanning or ambiguous columns need "
                "the original PDF for interpretation.",
            )
        )
    for issue in issues:
        logger.warning("Page %d: %s", issue.page_number, issue.message)
    return PageLayout(tuple(result), tuple(issues))
