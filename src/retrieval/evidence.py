"""Conservative evidence checks, not an answer generator or entailment model."""

import re
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
