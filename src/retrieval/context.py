"""Bounded, cited context selection with exact span provenance."""

from dataclasses import dataclass, replace
from typing import Any

from .lexical import BM25
from .models import SearchHit, SourceSpan, content_hash
from .text import sentence_spans


@dataclass(frozen=True)
class ContextSelection:
    text: str
    hits: tuple[SearchHit, ...]
    token_count: int
    omitted_ids: tuple[str, ...]


def slice_hit(hit: SearchHit, start: int, end: int) -> SearchHit:
    if not 0 <= start < end <= len(hit.text):
        raise ValueError("Invalid evidence passage bounds")
    sources = tuple(
        SourceSpan(
            span.page_number,
            span.section,
            max(span.start_char, start) - start,
            min(span.end_char, end) - start,
        )
        for span in hit.sources
        if span.start_char < end and span.end_char > start
    )
    if not sources:
        raise ValueError("Evidence passage has no source attribution")
    return replace(
        hit,
        chunk_id=f"{hit.chunk_id}:{start}:{end}",
        text=hit.text[start:end],
        pages=tuple(sorted({span.page_number for span in sources})),
        sections=tuple(dict.fromkeys(span.section for span in sources if span.section)),
        sources=sources,
        char_start=hit.char_start + start if hit.char_start is not None else None,
        parent_chunk_id=hit.parent_chunk_id or hit.chunk_id,
    )


def _count(text: str, tokenizer: Any) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False))


def _body_budgets(hits: list[SearchHit], tokenizer: Any, max_tokens: int) -> list[int]:
    """Distribute capacity after small passages and citation overhead are paid."""
    costs = [_count(hit.text, tokenizer) for hit in hits]
    headers = sum(_count(f"[{i}] {hit.citation}\n", tokenizer) for i, hit in enumerate(hits, 1))
    available = max(0, max_tokens - headers - 2 * len(hits))
    lower, upper = 0, max(costs, default=0)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if sum(min(cost, middle) for cost in costs) <= available:
            lower = middle
        else:
            upper = middle - 1
    return [min(cost, lower) for cost in costs]


def _render(hits: list[SearchHit]) -> str:
    return "\n\n".join(f"[{i}] {hit.citation}\n{hit.text}" for i, hit in enumerate(hits, 1))


def _focused_hit(hit: SearchHit, query: str, tokenizer: Any, budget: int) -> SearchHit | None:
    if _count(hit.text, tokenizer) <= budget:
        return hit
    spans = sentence_spans(hit.text)
    candidates = []
    for index, (start, end) in enumerate(spans):
        if _count(hit.text[start:end], tokenizer) > budget:
            # Long tables retain rows, including separators; never chop a value.
            row_start = start
            for row in hit.text[start:end].splitlines(keepends=True):
                row_end = row_start + len(row.rstrip())
                if row_end > row_start and _count(hit.text[row_start:row_end], tokenizer) <= budget:
                    candidates.append(slice_hit(hit, row_start, row_end))
                row_start += len(row)
            continue
        for _, next_end in spans[index + 1 :]:
            if _count(hit.text[start:next_end], tokenizer) > budget:
                break
            end = next_end
        candidates.append(slice_hit(hit, start, end))
    ranked = BM25(candidates).search(query, top_k=1)
    # When none of the query words occur, retain the leading complete passage.
    if ranked:
        return next(
            candidate for candidate in candidates if candidate.chunk_id == ranked[0].chunk_id
        )
    return candidates[0] if candidates else None


def select_context(
    hits: list[SearchHit], tokenizer: Any, *, max_tokens: int = 4096, query: str | None = None
) -> ContextSelection:
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if query is not None and (not isinstance(query, str) or not query.strip()):
        raise ValueError("query must be a nonempty string")
    # Give later hits room, but redistribute the space unused by short hits.
    # Final full-context tokenization below remains the authoritative budget check.
    budgets = _body_budgets(hits, tokenizer, max_tokens) if query else []
    selected: list[SearchHit] = []
    omitted = []
    seen = set()
    context = ""
    for index, original in enumerate(hits):
        hit = original
        if query:
            hit = _focused_hit(hit, query, tokenizer, budgets[index]) if budgets[index] else None
        if hit is None:
            omitted.append(original.chunk_id)
            continue
        identity = (hit.arxiv_id, hit.version, content_hash(hit.text))
        contained = any(
            prior.arxiv_id == hit.arxiv_id
            and prior.version == hit.version
            and prior.char_start is not None
            and hit.char_start is not None
            and prior.char_start <= hit.char_start
            and hit.char_start + len(hit.text) <= prior.char_start + len(prior.text)
            for prior in selected
        )
        if identity in seen or contained:
            omitted.append(original.chunk_id)
            continue
        block = f"[{len(selected) + 1}] {hit.citation}\n{hit.text}"
        candidate = f"{context}\n\n{block}" if context else block
        if _count(candidate, tokenizer) > max_tokens:
            omitted.append(original.chunk_id)
            continue
        selected.append(hit)
        seen.add(identity)
        context = candidate
    # Sentence boundaries and shorter citation headers can leave spare capacity.
    # Restore whole original passages when they now fit; never invent fragments.
    if query:
        originals = {hit.chunk_id: hit for hit in hits}
        for index, hit in enumerate(selected):
            if not hit.parent_chunk_id or hit.parent_chunk_id not in originals:
                continue
            replacement = [*selected]
            replacement[index] = originals[hit.parent_chunk_id]
            candidate = _render(replacement)
            if _count(candidate, tokenizer) <= max_tokens:
                selected = replacement
                context = candidate
    return ContextSelection(context, tuple(selected), _count(context, tokenizer), tuple(omitted))


def build_context(
    hits: list[SearchHit], tokenizer: Any, *, max_tokens: int = 4096, query: str | None = None
) -> str:
    """Backwards-compatible string API; pass query to focus long passages."""
    return select_context(hits, tokenizer, max_tokens=max_tokens, query=query).text
