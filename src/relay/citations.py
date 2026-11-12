"""Validate streamed claims before display; provenance is not semantic entailment."""

import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from retrieval.context import slice_hit
from retrieval.evidence import AnswerCoverage, assess_answer_coverage, infer_answer_parts

from .errors import RelayError
from .prompts import REFUSAL
from .tools import EvidenceSource, has_controls, strict_json


class CitationValidationError(RelayError):
    def __init__(
        self,
        message: str,
        *,
        source_id: str | None = None,
        quote: str | None = None,
    ) -> None:
        super().__init__("citation_validation", message)
        self.source_id = source_id
        self.quote = quote


class UnsupportedNumberError(RelayError):
    def __init__(self, numbers: set[str]) -> None:
        super().__init__(
            "unsupported_number", "A claimed number is absent from its supporting quotations."
        )
        self.numbers = tuple(sorted(numbers))


_FORMAT_TRANSLATION = str.maketrans(
    {
        "\u2212": "-",
        "\u00d7": "x",
        "\u2192": "->",
        "\u2190": "<-",
        "\u2265": ">=",
        "\u2264": "<=",
        "\u2260": "!=",
        "\u00b7": "*",
        "\u2013": "-",
        "\u2014": "-",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
)


def _canonical_positions(text: str) -> tuple[str, list[int]]:
    """Normalize documented rendering differences while preserving content.

    This ignores formatting that the extractor and model commonly render differently:
    whitespace, table pipes, superscript markers, line-break hyphenation, slash-style
    fractions, and Unicode mathematical symbols. Words, numbers, signs, punctuation
    and ordering remain exact, so paraphrases and fabricated quotations still fail.
    """
    characters: list[tuple[str, int]] = []
    for index, original in enumerate(text):
        for character in unicodedata.normalize("NFKC", original):
            characters.append((character, index))

    cleaned: list[tuple[str, int]] = []
    for index, (character, position) in enumerate(characters):
        if character == "-":
            before = index - 1
            while before >= 0 and characters[before][0].isspace():
                before -= 1
            after = index + 1
            while after < len(characters) and characters[after][0].isspace():
                after += 1
            if (
                before >= 0
                and after < len(characters)
                and (characters[before][0].isalnum() or characters[before][0] == "_")
                and characters[after][0].isalpha()
            ):
                continue
        cleaned.append((character, position))

    output: list[str] = []
    positions: list[int] = []
    for character, position in cleaned:
        if character in "|/^{}":
            continue
        for mapped in character.translate(_FORMAT_TRANSLATION):
            if mapped.isspace():
                continue
            output.append(mapped)
            positions.append(position)
    return "".join(output), positions


def _numbers(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).replace("−", "-")
    values = re.findall(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)*", text)
    return {
        value.replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", value) else value
        for value in values
    }


@dataclass(frozen=True)
class Citation:
    source_id: str
    paper_title: str
    arxiv_id: str
    version: int
    pages: tuple[int, ...]
    source_url: str
    chunk_id: str
    char_start: int | None
    quote: str

    @property
    def label(self) -> str:
        pages = ", ".join(map(str, self.pages))
        prefix = "p." if len(self.pages) == 1 else "pp."
        return f"{self.paper_title} (arXiv:{self.arxiv_id}v{self.version}, {prefix} {pages})"


@dataclass(frozen=True)
class Claim:
    text: str
    citations: tuple[Citation, ...]

    def render(self) -> str:
        return (
            self.text
            + " "
            + " ".join(
                f"[{identifier}]"
                for identifier in dict.fromkeys(c.source_id for c in self.citations)
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_claim(value: dict[str, Any], sources: dict[str, EvidenceSource]) -> Claim:
    if set(value) != {"type", "text", "evidence"}:
        raise RelayError("citation_validation", "A claim has unexpected or missing fields.")
    text, evidence = value["text"], value["evidence"]
    if (
        not isinstance(text, str)
        or not 1 <= len(text.strip()) <= 1600
        or has_controls(text)
        or re.search(r"\[S\d|https?://|arXiv:", text, re.I)
    ):
        raise RelayError(
            "citation_validation",
            "The claim text contains invalid formatting or free-form citations.",
        )
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
        raise RelayError(
            "citation_validation", "Every claim requires one to three supporting citations."
        )
    citations = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"source_id", "quote"}:
            raise RelayError("citation_validation", "Invalid citation structure.")
        identifier, quote = item["source_id"], item["quote"]
        if not isinstance(identifier, str) or identifier not in sources:
            raise RelayError(
                "citation_validation", "A citation references evidence that was not retrieved."
            )
        if not isinstance(quote, str) or not 12 <= len(quote.strip()) <= 1200:
            raise RelayError(
                "citation_validation", "A citation needs a nonempty supporting quotation."
            )
        hit = sources[identifier].hit
        normalized, offsets = _canonical_positions(hit.text)
        needle = _canonical_positions(quote)[0]
        start = normalized.find(needle) if needle else -1
        if start < 0:
            raise CitationValidationError(
                "The supporting quotation is absent from the cited passage.",
                source_id=identifier,
                quote=quote,
            )
        quoted = slice_hit(hit, offsets[start], offsets[start + len(needle) - 1] + 1)
        citations.append(
            Citation(
                identifier,
                quoted.paper_title,
                quoted.arxiv_id,
                quoted.version,
                quoted.pages,
                quoted.source_url,
                hit.parent_chunk_id or hit.chunk_id,
                quoted.char_start,
                quoted.text,
            )
        )
    unsupported = _numbers(text) - set().union(*(_numbers(c.quote) for c in citations))
    if unsupported:
        raise UnsupportedNumberError(unsupported)
    return Claim(text.strip(), tuple(citations))


def _object_end(text: str) -> int | None:
    """Return the end of the first complete JSON object, or None while incomplete.

    Models do not always honor the requested JSON Lines framing and may emit
    adjacent objects on one line, so streaming must not rely on newline splits.
    """
    if not text or text[0] != "{":
        raise RelayError("stream_format", "Expected a structured answer object.")
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
        elif character in "}]":
            depth -= 1
            if depth < 0:
                raise RelayError("stream_format", "Unbalanced structured answer output.")
            if depth == 0:
                return index + 1
    return None


class ClaimStream:
    """Buffer complete JSON objects, validate each, then publish readable text."""

    def __init__(
        self,
        sources: list[EvidenceSource],
        emit: Callable[[str], None],
        *,
        question: str = "",
    ) -> None:
        self.sources = {s.source_id: s for s in sources}
        self.emit = emit
        self.buffer = ""
        self.claims: list[Claim] = []
        self.refused = False
        self.done = False
        self.validation_seconds = 0.0
        self.last_record: dict[str, Any] | None = None
        self.failure: dict[str, Any] | None = None
        self.coverage_plan = infer_answer_parts(question)
        self.coverage: AnswerCoverage | None = None

    def feed(self, delta: str) -> None:
        self.buffer += delta
        try:
            self._consume()
            if len(self.buffer) > 16000:
                raise RelayError("stream_format", "A generated claim exceeds the line-size limit.")
        except RelayError as error:
            self._record_failure(error)
            raise

    def _record_failure(
        self,
        error: RelayError,
        *,
        candidate_record: Any | None = None,
        raw_record: str | None = None,
    ) -> None:
        if self.failure is not None:
            return
        self.failure = {
            "error": error.to_dict(),
            "stream_suffix": self.buffer[:16000],
            "raw_record": raw_record,
            "candidate_record": candidate_record,
            "last_record": self.last_record,
            "rejected_quote": getattr(error, "quote", None),
            "source_id": getattr(error, "source_id", None),
            "accepted_claim_count": len(self.claims),
            "accepted_claims": [claim.to_dict() for claim in self.claims],
            "unsupported_numbers": list(getattr(error, "numbers", ())),
            "answer_coverage": asdict(self.coverage) if self.coverage is not None else None,
        }

    def _consume(self) -> None:
        while True:
            self.buffer = self.buffer.lstrip()
            if not self.buffer:
                return
            end = _object_end(self.buffer)
            if end is None:
                return
            raw, self.buffer = self.buffer[:end], self.buffer[end:]
            try:
                value = strict_json(raw)
            except RelayError as error:
                self._record_failure(error, raw_record=raw)
                raise
            try:
                self._value(value)
            except RelayError as error:
                self._record_failure(error, candidate_record=value)
                raise

    def _value(self, value: Any) -> None:
        start = time.perf_counter()
        rendered = None
        try:
            if self.done:
                raise RelayError("stream_format", "Unexpected content after the answer terminator.")
            if not isinstance(value, dict):
                raise RelayError("stream_format", "Expected a structured answer record.")
            kind = value.get("type")
            if kind == "done" and set(value) == {"type"}:
                if not self.claims and not self.refused:
                    raise RelayError("stream_format", "The answer ended without any result.")
                self.done = True
            elif (
                kind == "refusal"
                and set(value) == {"type"}
                and not self.claims
                and not self.refused
            ):
                self.refused = True
                rendered = REFUSAL
            elif kind == "claim" and not self.refused and len(self.claims) < 6:
                claim = validate_claim(value, self.sources)
                self.claims.append(claim)
                rendered = claim.render()
            else:
                raise RelayError("stream_format", "Unexpected, mixed or excessive answer records.")
        finally:
            self.validation_seconds += time.perf_counter() - start
        self.last_record = value
        if rendered is not None:
            self.emit(rendered + "\n")

    def finish(self) -> None:
        try:
            self._consume()
            if self.buffer.strip():
                raise RelayError("stream_format", "The answer ended with an incomplete record.")
            if not self.done:
                raise RelayError(
                    "incomplete_answer", "The answer did not include its completion marker."
                )
            if not self.refused:
                self.coverage = assess_answer_coverage(
                    self.coverage_plan,
                    tuple(
                        (claim.text, tuple(citation.quote for citation in claim.citations))
                        for claim in self.claims
                    ),
                )
                if self.coverage.status not in {"complete", "not_required"}:
                    raise RelayError(
                        "incomplete_answer",
                        "The answer does not establish coverage of every requested part. "
                        "Try asking for each part separately.",
                    )
        except RelayError as error:
            self._record_failure(error)
            raise
        self.buffer = ""
