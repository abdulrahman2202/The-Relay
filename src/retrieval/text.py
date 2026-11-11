"""Shared, deterministic text normalization and evidence boundaries."""

import re
import unicodedata

# Match the audit's fixed lexical settings; no corpus-specific vocabulary tuning.
STOPWORDS = frozenset(
    "a an and are as at be been by did do does for from had has have how in into is it "
    "its of on or that the their there these this to was were what when where which "
    "who why will with would".split()
)


def dehyphenate(text: str) -> str:
    """Join alphabetic line-break hyphenation, leaving numeric ranges unchanged."""
    return re.sub(r"(?<=[^\W\d_])-\s*\n\s*(?=[^\W\d_])", "", text)


def lexical_tokens(text: str) -> list[str]:
    normalized = dehyphenate(unicodedata.normalize("NFKC", text)).casefold()
    terms = re.findall(r"[^\W\d_]+|\d+(?:\.\d+)?", normalized, re.UNICODE)
    return [term for term in terms if term not in STOPWORDS]


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Keep decimals and wrapped lines intact; preserve exact source offsets."""
    breaks = [0]
    for match in re.finditer(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z\u00c0-\u024f])", text):
        # Common scientific abbreviations are not sentence endings.
        if re.search(r"\b(?:Fig|Eq|Dr|Mr|Ms|vs|al)\.$", text[: match.start()]):
            continue
        breaks.append(match.end())
    breaks.append(len(text))
    spans = []
    for start, end in zip(breaks, breaks[1:], strict=False):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append((start, end))
    return spans
