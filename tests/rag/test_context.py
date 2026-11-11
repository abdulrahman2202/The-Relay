from dataclasses import replace

from retrieval.context import build_context, select_context
from retrieval.models import SearchHit, SourceSpan


def make_hit(identifier, text, *, paper="2410.00037", page=1, start=0):
    return SearchHit(
        identifier,
        text,
        "Paper",
        paper,
        1,
        (page,),
        ("Methods",),
        (SourceSpan(page, "Methods", 0, len(text)),),
        0.2,
        char_start=start,
    )


def test_oversized_first_hit_does_not_hide_a_later_fitting_passage(tokenizer):
    large = make_hit("large", "irrelevant " * 500)
    small = make_hit("small", "The latency is 160 ms.", page=2, start=len(large.text))
    context = select_context([large, small], tokenizer, max_tokens=70)
    assert [h.chunk_id for h in context.hits] == ["small"]
    assert "160 ms" in context.text
    assert context.omitted_ids == ("large",)
    assert context.token_count == len(tokenizer.encode(context.text)) <= 70


def test_query_focusing_keeps_the_answer_and_correct_page(tokenizer):
    background = "This paragraph discusses unrelated background.\n\n" * 40
    evidence = "Moshi has theoretical latency 160 ms and practical latency 200 ms."
    text = background + evidence
    original = make_hit("long", text, start=100)
    original = replace(
        original,
        pages=(1, 2),
        sources=(
            SourceSpan(1, "Introduction", 0, len(background)),
            SourceSpan(2, "Latency", len(background), len(text)),
        ),
    )
    selected = select_context(
        [original], tokenizer, max_tokens=65, query="Moshi theoretical and practical latency"
    )
    assert "160 ms" in selected.text and "200 ms" in selected.text
    passage = selected.hits[0]
    assert passage.pages == (2,)
    assert passage.source_url.endswith("#page=2")
    assert passage.parent_chunk_id == "long"
    assert passage.char_start == 100 + len(background)
    assert passage.retrieval_method == "vector"
    assert (
        original.text[passage.char_start - 100 : passage.char_start - 100 + len(passage.text)]
        == passage.text
    )
    assert selected.token_count <= 65


def test_overlap_deduplication_keeps_distinct_paper_attribution(tokenizer):
    first = make_hit("first", "Measured theoretical latency is 160 ms.")
    duplicate = replace(first, chunk_id="duplicate")
    other_paper = replace(first, chunk_id="other", arxiv_id="2507.07955")
    result = select_context([first, duplicate, other_paper], tokenizer)
    assert [h.chunk_id for h in result.hits] == ["first", "other"]


def test_citation_and_separator_tokens_count_toward_the_exact_budget(tokenizer):
    hits = [make_hit("a", "First result."), make_hit("b", "Second result.", page=2, start=50)]
    full = build_context(hits, tokenizer)
    count = len(tokenizer.encode(full))
    assert build_context(hits, tokenizer, max_tokens=count) == full
    smaller = select_context(hits, tokenizer, max_tokens=count - 1)
    assert len(smaller.hits) == 1
    assert smaller.token_count <= count - 1


def test_unused_short_hit_budget_preserves_long_evidence(tokenizer):
    first = make_hit(
        "long", "Background. " * 12 + "Moshi latency is 160 ms and 200 ms in practice."
    )
    second = make_hit("short", "Related evidence.", page=2, start=1000)
    full = build_context([first, second], tokenizer)
    budget = len(tokenizer.encode(full))
    selected = select_context([first, second], tokenizer, max_tokens=budget, query="Moshi latency")
    assert selected.text == full
    assert selected.token_count == budget
