"""Token windows that retain the exact extracted text and its source spans."""

from bisect import bisect_left, bisect_right
from typing import Any

from .config import MODEL_NAME, MODEL_REVISION, PIPELINE_VERSION, RagConfig
from .models import Chunk, ExtractedPaper, SourceSpan, stable_hash
from .text import sentence_spans


def _inside_word(text: str, position: int) -> bool:
    return 0 < position < len(text) and text[position - 1].isalnum() and text[position].isalnum()


def chunk_paper(document: ExtractedPaper, tokenizer: Any, config: RagConfig) -> list[Chunk]:
    """Chunk one paper using the embedding model's tokenizer, without special tokens.

    Boundary windows stay within sections and prefer complete sentences/tables.
    Fixed windows retain the original configurable behavior. Duplicate pages are omitted
    with their original page numbers retained in the extraction report. Source spans
    retain all page/section transitions within a window.
    """
    parts: list[str] = []
    spans: list[SourceSpan] = []
    position = 0
    tables: list[tuple[int, int]] = []
    for page in document.pages:
        if page.duplicate_of is not None:
            continue
        for section in page.sections:
            spans.append(
                SourceSpan(
                    page.page_number,
                    section.section,
                    position + section.start_char,
                    position + section.end_char,
                )
            )
        tables.extend(
            (position + r.start_char, position + r.end_char)
            for r in page.regions
            if r.kind == "table"
        )
        parts.append(page.text + "\n")
        position += len(page.text) + 1
    text = "".join(parts)
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
        verbose=False,
    )
    offsets = encoded["offset_mapping"]
    if not offsets:
        return []
    starts = [offset[0] for offset in offsets]
    section_ends = [len(offsets)]
    preferred = set()
    atomic = []
    if config.chunking == "boundary":
        for previous, current in zip(spans, spans[1:], strict=False):
            if previous.section != current.section:
                previous_text = " ".join(text[previous.start_char : previous.end_char].split())
                # A parent heading immediately followed by a subsection has no
                # standalone evidence. Carry it into the child's first chunk.
                if previous_text != previous.section:
                    section_ends.append(bisect_left(starts, current.start_char))
        section_ends = sorted(set(section_ends))
        preferred.update(bisect_left(starts, end) for _, end in sentence_spans(text))
        for left, right in tables:
            a, b = bisect_left(starts, left), bisect_left(starts, right)
            preferred.update((a, b))
            if b - a <= config.chunk_size:
                atomic.append((a, b))
            else:
                # Large tables split at row boundaries, retaining complete cells.
                cursor = left
                for row in text[left:right].splitlines(keepends=True):
                    cursor += len(row)
                    preferred.add(bisect_left(starts, cursor))
        preferred = {end for end in preferred if not any(a < end < b for a, b in atomic)}
    preferred_ends = sorted(preferred)
    chunks: list[Chunk] = []
    start = 0
    while start < len(offsets):
        end = min(start + config.chunk_size, len(offsets))
        section_end = section_ends[bisect_right(section_ends, start)]
        if config.chunking == "boundary":
            end = min(end, section_end)
            for left, right in atomic:
                if left < end < right and left > start:
                    end = left
            candidate = bisect_right(preferred_ends, end) - 1
            if candidate >= 0 and preferred_ends[candidate] > start:
                end = preferred_ends[candidate]
            while end > start and _inside_word(text, offsets[end - 1][1]):
                end -= 1
            if end <= start:
                raise ValueError("chunk_size cannot fit one complete word; increase chunk_size")
        char_start = offsets[start][0]
        # A cut through a WordPiece can change tokenization of the returned substring.
        # Recount it, shrinking if needed, so chunk_size is an actual upper bound.
        while True:
            char_end = offsets[end - 1][1]
            chunk_text = text[char_start:char_end]
            token_count = len(
                tokenizer.encode(
                    chunk_text, add_special_tokens=False, truncation=False, verbose=False
                )
            )
            if token_count <= config.chunk_size:
                break
            end -= 1
            if config.chunking == "boundary":
                while end > start and _inside_word(text, offsets[end - 1][1]):
                    end -= 1
            if end <= start:
                raise ValueError("chunk_size is too small for this tokenizer boundary")
        chunk_sources = tuple(
            SourceSpan(
                span.page_number,
                span.section,
                max(span.start_char, char_start) - char_start,
                min(span.end_char, char_end) - char_start,
            )
            for span in spans
            if span.start_char < char_end and span.end_char > char_start
        )
        identity = {
            "pipeline": PIPELINE_VERSION,
            "document": document.paper.document_id,
            "tokenizer": f"{MODEL_NAME}@{MODEL_REVISION}",
            "settings": config.indexing_settings,
            "token_start": start,
            "token_end": end,
            "text": chunk_text,
        }
        chunks.append(
            Chunk(
                stable_hash(identity),
                document.paper,
                chunk_text,
                token_count,
                start,
                end,
                char_start,
                char_end,
                chunk_sources,
            )
        )
        if end == len(offsets):
            break
        next_start = max(start + 1, end - config.overlap)
        if config.chunking == "boundary":
            if end == section_end:
                next_start = end
            else:
                candidate = bisect_left(preferred_ends, next_start)
                if candidate < len(preferred_ends) and preferred_ends[candidate] < end:
                    next_start = preferred_ends[candidate]
                while next_start < end and _inside_word(text, offsets[next_start][0]):
                    next_start += 1
        start = next_start
    return chunks
