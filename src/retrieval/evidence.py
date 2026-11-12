"""Conservative evidence checks, not an answer generator or entailment model."""

import re
import unicodedata
from dataclasses import dataclass

from .catalog import PAPERS
from .models import SearchHit
from .text import lexical_tokens


@dataclass(frozen=True)
class EvidenceRequirement:
    """At least one literal alternative must occur in the specified paper's evidence.

    Empty alternatives mean paper presence only. Separate requirements are ANDed;
    alternatives are ORed. This permits explicit model/metric/device/unit checks.
    """

    label: str
    alternatives: tuple[str, ...] = ()
    arxiv_id: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Evidence requirement needs a label")
        if not self.alternatives and self.arxiv_id is None:
            raise ValueError("Evidence requirement needs alternatives or a paper")
        if any(not lexical_tokens(value) for value in self.alternatives):
            raise ValueError("Evidence alternatives must contain searchable terms")
        if self.arxiv_id is not None and self.arxiv_id not in {p.arxiv_id for p in PAPERS}:
            raise ValueError("Evidence paper must be one of the supplied papers")


@dataclass(frozen=True)
class EvidenceAssessment:
    status: str
    reason: str
    missing: tuple[str, ...]

    @property
    def refused(self) -> bool:
        return self.status == "insufficient_evidence"


def infer_requirements(
    query: str, *, arxiv_id: str | None = None
) -> tuple[EvidenceRequirement, ...]:
    """Recognize high-specificity constraints; do not pretend to parse every claim.

    Callers can supply explicit requirements for facts this small local heuristic
    cannot recognize. No question/answer lookup or evaluation annotations are used.
    """
    aliases = {
        "1706.03762": r"attention is all you need",
        "2410.00037": r"\b(?:moshi|mimi|helium)\b",
        "2507.07955": r"\bh[- ]?net\b|dynamic chunking",
    }
    scopes = [paper for paper, pattern in aliases.items() if re.search(pattern, query, re.I)]
    if arxiv_id and arxiv_id not in scopes:
        scopes.append(arxiv_id)
    requirements = [
        EvidenceRequirement(f"passage from arXiv:{paper}", arxiv_id=paper) for paper in scopes
    ]
    phrases: list[tuple[str, ...]] = []
    phrases.extend((match.group(),) for match in re.finditer(r"\b[A-Z][A-Z0-9]{2,}\b", query))
    phrases.extend(
        (match.group(),)
        for match in re.finditer(
            r"\bp\d{2}\b|\biOS\b|\bAndroid\b|\biPhone\s+\d+(?:\s+(?:Pro|Max|Plus)){0,2}\b",
            query,
            re.I,
        )
    )
    for match in re.finditer(
        r"\b(\d+(?:\.\d+)?)\s*[- ]?\s*(billion|million|b|m)\s*[- ]?\s*parameters?\b",
        query,
        re.I,
    ):
        value, unit = match.groups()
        units = ("b", "billion") if unit.casefold() in {"b", "billion"} else ("m", "million")
        phrases.append(
            tuple(f"{value} {u} {p}" for u in units for p in ("parameter", "parameters"))
        )
    for match in re.finditer(r"\b(?:in|as of|during)\s+(?:[A-Za-z]+\s+)?(20\d{2})\b", query, re.I):
        phrases.append((match.group(1),))
    seen = set()
    for alternatives in phrases:
        key = tuple(" ".join(lexical_tokens(text)) for text in alternatives)
        if key in seen:
            continue
        seen.add(key)
        for scope in scopes or [None]:
            label = alternatives[0] + (f" in arXiv:{scope}" if scope else "")
            requirements.append(EvidenceRequirement(label, alternatives, scope))
    return tuple(requirements)


def assess_evidence(
    hits: list[SearchHit] | tuple[SearchHit, ...], requirements: tuple[EvidenceRequirement, ...]
) -> EvidenceAssessment:
    if not hits:
        return EvidenceAssessment(
            "insufficient_evidence", "No cited evidence fits the request.", ("cited passage",)
        )
    missing = []
    normalized = {hit.chunk_id: " " + " ".join(lexical_tokens(hit.text)) + " " for hit in hits}
    for requirement in requirements:
        candidates = [
            hit
            for hit in hits
            if requirement.arxiv_id is None or hit.arxiv_id == requirement.arxiv_id
        ]
        found = (
            bool(candidates)
            if not requirement.alternatives
            else any(
                " " + " ".join(lexical_tokens(alternative)) + " " in normalized[hit.chunk_id]
                for hit in candidates
                for alternative in requirement.alternatives
            )
        )
        if not found:
            missing.append(requirement.label)
    if missing:
        return EvidenceAssessment(
            "insufficient_evidence",
            "The retrieved context does not support all requested constraints.",
            tuple(missing),
        )
    return EvidenceAssessment(
        "candidate_evidence",
        "Cited passages pass the requested literal constraints; "
        "this does not establish full answer entailment.",
        (),
    )


@dataclass(frozen=True)
class AnswerPart:
    """A named quantity and the literal assertion forms that can establish it.

    Patterns capture values from text, never supply expected answers. This is a
    deliberately bounded grammar, not semantic entailment or a question lookup.
    """

    label: str
    question_pattern: str
    assertions: tuple[str, ...]
    table_column: str | None = None
    table_row: str | None = None


@dataclass(frozen=True)
class QuestionParts:
    required: tuple[AnswerPart, ...]
    unrecognized: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerCoverage:
    status: str
    required: tuple[str, ...]
    missing: tuple[str, ...]
    unrecognized: tuple[str, ...] = ()


_VALUE = r"(?P<value>[+-]?\d+(?:[.,]\d+)*(?:e[+-]?\d+)?)(?!\d|[.,]\d|e[+-]?\d)"
_ASSIGN = r"\s*(?:is|are|was|were|of|equals?|=|:)\s*"


def _quantity(label: str, question: str, *names: str) -> AnswerPart:
    patterns = tuple(rf"\b(?:{name}){_ASSIGN}{_VALUE}" for name in names)
    return AnswerPart(label, question, patterns)


_ANSWER_PARTS = (
    AnswerPart(
        "routing threshold",
        r"\bthreshold\b",
        (
            rf"\b(?:routing |probability |boundary )?threshold{_ASSIGN}{_VALUE}",
            rf"\bpt\s*(?:>=|>)\s*{_VALUE}",
            rf"\b(?:probability|routing score)\s*(?:is\s*)?(?:at least|>=)\s*{_VALUE}",
        ),
    ),
    AnswerPart(
        "first-position boundary probability",
        r"\b(?:first (?:position|token)|initial (?:boundary )?probability|p1)\b",
        (
            rf"\bp1\s*=\s*{_VALUE}",
            rf"\b(?:first(?: position| token)?|initial)(?: boundary)? probability"
            rf"{_ASSIGN}{_VALUE}",
            rf"\bboundary probability (?:at|for) the first (?:position|token)"
            rf"{_ASSIGN}{_VALUE}",
        ),
    ),
    AnswerPart(
        "theoretical latency",
        r"\btheoretical\b(?=.*\blatenc)",
        (
            rf"\btheoretical latency{_ASSIGN}{_VALUE}",
            rf"{_VALUE}\s*(?:ms|milliseconds|seconds|s)\s+(?:theoretically|in theory)\b",
        ),
    ),
    AnswerPart(
        "practical latency",
        r"\bpractical\b(?=.*\blatenc)",
        (
            rf"\bpractical latency{_ASSIGN}{_VALUE}",
            rf"{_VALUE}\s*(?:ms|milliseconds|seconds|s)\s+in practice\b",
        ),
    ),
    AnswerPart(
        "optimizer",
        r"\boptimizer\b",
        (
            r"\b(?P<value>[a-z][a-z0-9]*) optimizer\b",
            rf"\boptimizer{_ASSIGN}(?P<value>[a-z][a-z0-9]*)\b",
        ),
    ),
    _quantity("beta1", r"\bbeta(?:\s*1\b|\b(?!\s*2\b))", r"beta\s*1"),
    _quantity("beta2", r"\bbeta(?:\s*2\b|\b(?!\s*1\b))", r"beta\s*2"),
    AnswerPart(
        "warmup steps",
        r"\bwarmup\b",
        (rf"\bwarmup steps{_ASSIGN}{_VALUE}", rf"{_VALUE}\s+warmup steps\b"),
    ),
    AnswerPart(
        "attention heads",
        r"\b(?:attention )?heads\b",
        (rf"\bh\s*=\s*{_VALUE}", rf"{_VALUE}\s+(?:parallel )?(?:attention )?heads\b"),
    ),
    AnswerPart(
        "key dimension",
        r"\bkey\b(?=.*\bdimensions?\b)",
        (
            rf"\bkey(?: and value)? dimensions?{_ASSIGN}{_VALUE}",
            rf"\bdk\s*=\s*(?:dv\s*=\s*)?(?:dmodel/h\s*=\s*)?{_VALUE}",
        ),
    ),
    AnswerPart(
        "value dimension",
        r"\bvalue\b(?=.*\bdimensions?\b)",
        (
            rf"\bvalue dimensions?{_ASSIGN}{_VALUE}",
            rf"\bdv\s*=\s*(?:dmodel/h\s*=\s*)?{_VALUE}",
        ),
    ),
    AnswerPart(
        "quantizers",
        r"\bquantizers?\b",
        (rf"\bq\s*=\s*{_VALUE}", rf"{_VALUE}\s+quantizers\b"),
    ),
    _quantity("codebook size", r"\bcodebook\b", r"codebook (?:size|entries)", r"na"),
    AnswerPart(
        "frame rate",
        r"\bframe rate\b",
        (rf"\bframe rate{_ASSIGN}{_VALUE}", rf"{_VALUE}\s*hz\b"),
    ),
    AnswerPart(
        "bitrate",
        r"\bbit ?rate\b",
        (rf"\bbit ?rate{_ASSIGN}{_VALUE}", rf"{_VALUE}\s*kbps\b"),
    ),
    AnswerPart(
        "parameters",
        r"\bparameters?\b",
        (r"(?P<value>\d+(?:\.\d+)?\s*(?:b|m|billion|million)?)\s*[- ]?parameters?\b",),
    ),
    AnswerPart(
        "training tokens",
        r"\b(?:pretraining|training) tokens\b",
        (r"(?P<value>\d+(?:\.\d+)?\s*(?:t|b|trillion|billion)?)\s+tokens\b",),
    ),
)


def _coverage_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate(str.maketrans({"β": "beta", "−": "-", "≥": ">=", "≤": "<="}))
    text = re.sub(r"\b(p|d)_?\{?([1tkv])\}?", r"\1\2", text)
    text = re.sub(r"(?<=[a-z])[-‐‑_](?=[a-z])", " ", text)
    return " ".join(text.split())


def _table_parts(question: str) -> tuple[AnswerPart, ...]:
    """Bind explicit translation columns or named-model accuracy comparisons."""
    models = tuple(
        match.group()
        for match in re.finditer(
            r"\b(?:transformer|h net)(?:\s*\((?:big|base|\d+[- ]stage)\))?", question
        )
    )
    parts = []
    if "bleu" in question:
        for language, short in (("german", "de"), ("french", "fr")):
            name = f"english to {language}"
            if name not in question:
                continue
            parts.append(
                AnswerPart(
                    name + " BLEU",
                    rf"\b{name}\b",
                    (
                        rf"\b{name}(?: bleu)?(?: score)?{_ASSIGN}{_VALUE}",
                        rf"{_VALUE}(?: bleu)?(?: for| on| in)\s+{name}\b",
                    ),
                    rf"(?:{name}|en {short})",
                    re.escape(models[0]) if len(models) == 1 else None,
                )
            )
    metric = re.search(r"\bwhat ([a-z0-9]+(?: [a-z0-9]+){0,3}) accuracies\b", question)
    if metric and len(models) > 1:
        column = re.escape(metric[1])
        for model in models:
            name = re.escape(model)
            parts.append(
                AnswerPart(
                    model + " " + metric[1] + " accuracy",
                    name,
                    (
                        rf"\b{name}(?: {column})? accuracy{_ASSIGN}{_VALUE}",
                        rf"\b{name}\s+(?:achieves|reports|scores)\s+{_VALUE}",
                    ),
                    column,
                    name,
                )
            )
    return tuple(parts)


def infer_answer_parts(question: str) -> QuestionParts:
    """Recognize explicit coordinated quantities; reject unrecognized conjuncts.

    There are no expected numbers, paper IDs or evaluation question IDs here.
    Single requests outside this grammar retain the existing citation contract.
    Unsupported multipart requests cannot silently bypass the coverage check.
    """
    text = _coverage_text(question)
    request = re.search(
        r"\b(?:what|which|how|why|when|where|give|list|report|compare|tell)\b", text
    )
    body = text[request.start() :] if request else text
    clauses = tuple(
        clause.strip(" ,.")
        for clause in re.split(
            r"\b(?:and|also|plus|as well as|along with|together with|versus|vs)\b|[,;?&]",
            body,
        )
        if clause.strip(" ,.")
    )
    parts = tuple(part for part in _ANSWER_PARTS if re.search(part.question_pattern, body))
    parts += _table_parts(body)
    if len(clauses) <= 1 and len(parts) <= 1:
        if re.match(r"(?:compare|contrast)\b", body):
            return QuestionParts((), (body,))
        return QuestionParts(())
    unrecognized = ()
    if len(clauses) > 1 or len(parts) > 1:
        # Match the selector in the whole question to allow shared nouns, such as
        # "theoretical and practical latency" or "key and value dimensions".
        spans = [
            match.span() for part in parts for match in re.finditer(part.question_pattern, body)
        ]
        cursor = 0
        unknown = []
        for clause in clauses:
            start = body.index(clause, cursor)
            end = start + len(clause)
            cursor = end
            explanatory = re.search(
                r"\b(?:why|how (?!many\b|much\b)|explain|describe|justify|compare|contrast)\b",
                clause,
            )
            if explanatory or not any(start <= left < end for left, _ in spans):
                unknown.append(clause)
        unrecognized = tuple(unknown)
    return QuestionParts(parts, unrecognized)


def _asserted_values(part: AnswerPart, text: str) -> set[str]:
    text = _coverage_text(text)
    # A question or an explicitly withheld answer is not an asserted value.
    if "?" in text or re.search(r"\b(?:unknown|unspecified|not reported|not provided)\b", text):
        return set()
    values = {
        " ".join(match["value"].replace(",", "").split())
        for pattern in part.assertions
        for match in re.finditer(pattern, text)
    }
    if part.label in {"parameters", "training tokens"}:
        scales = {"million": "m", "billion": "b", "trillion": "t", "m": "m", "b": "b", "t": "t"}
        values = {
            re.sub(r"\s*(million|billion|trillion|[mbt])$", lambda m: scales[m[1]], value)
            for value in values
        }
    return values - {"the", "an", "a", "which", "what", "no", "not"}


def _table_values(part: AnswerPart, quotations: tuple[str, ...]) -> set[str]:
    if part.table_column is None:
        return set()
    rows = [
        tuple(_coverage_text(cell) for cell in line.strip().strip("|").split("|"))
        for quote in quotations
        for line in quote.splitlines()
        if "|" in line
    ]
    values = set()
    for header in rows:
        columns = [
            index
            for index, cell in enumerate(header)
            if re.search(rf"\b{part.table_column}\b", cell)
        ]
        if len(columns) != 1:
            continue
        for row in rows:
            if len(row) != len(header) or part.table_row is None:
                continue
            if not re.fullmatch(part.table_row, row[0]):
                continue
            value = row[columns[0]]
            if re.fullmatch(_VALUE, value):
                values.add(value.replace(",", ""))
    return values


def assess_answer_coverage(
    plan: QuestionParts, claims: tuple[tuple[str, tuple[str, ...]], ...]
) -> AnswerCoverage:
    """Check part/value pairs in already validated claims and their own quotes.

    A part present only in a quotation or another claim's evidence is insufficient.
    Duplicated claims cannot replace a missing part; one claim may cover many parts.
    This establishes bounded literal coverage, not unrestricted factual correctness.
    """
    if not plan.required and not plan.unrecognized:
        return AnswerCoverage("not_required", (), ())
    missing = []
    for part in plan.required:
        covered = False
        for text, quotations in claims:
            asserted = _asserted_values(part, text)
            supported = set().union(*(_asserted_values(part, quote) for quote in quotations))
            supported.update(_table_values(part, quotations))
            if asserted and asserted <= supported:
                covered = True
                break
        if not covered:
            missing.append(part.label)
    status = "unrecognized" if plan.unrecognized else ("incomplete" if missing else "complete")
    return AnswerCoverage(
        status, tuple(part.label for part in plan.required), tuple(missing), plan.unrecognized
    )
