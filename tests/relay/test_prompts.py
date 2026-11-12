import json
from dataclasses import replace

import pytest

from relay.citations import ClaimStream
from relay.prompts import ANSWER, PROMPT_VERSION
from relay.tools import EvidenceSource
from retrieval.models import SourceSpan

EXAMPLES = ANSWER.split("Example: ")[1:]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda value: value.splitlines()[0])
def test_prompt_examples_are_valid_evidence_first_claim_streams(source, example):
    sources, records = [], []
    for line in example.splitlines()[1:]:
        if line.startswith("Source "):
            identifier, encoded = line.removeprefix("Source ").split(": ", 1)
            text = json.loads(encoded)
            hit = replace(
                source.hit,
                text=text,
                sources=(SourceSpan(1, "Illustrative evidence", 0, len(text)),),
                pages=(1,),
            )
            sources.append(EvidenceSource(identifier, hit, "example"))
        elif line.startswith("{"):
            record = json.loads(line)
            if record["type"] == "claim":
                assert list(record) == ["type", "evidence", "text"]
                assert record["evidence"][0]["quote"] in [s.hit.text for s in sources]
            records.append(line)
    question = (
        "What is the routing threshold and initial boundary probability?"
        if example.startswith("both parts")
        else ""
    )
    parser = ClaimStream(sources, lambda text: None, question=question)
    for character in "\n".join(records):
        parser.feed(character)
    parser.finish()
    assert parser.done and parser.claims and parser.failure is None
    assert records[-1] == '{"type":"done"}'


def test_formula_example_keeps_literal_backslashes_in_decoded_math():
    example = next(example for example in EXAMPLES if example.startswith("formula"))
    claims = [
        json.loads(line) for line in example.splitlines() if line.startswith('{"type":"claim"')
    ]
    assert r"1/\sqrt{m}" in claims[0]["text"]
    assert r"1/\sqrt{m}" in claims[0]["evidence"][0]["quote"]
    assert len(claims) == 2 and "gradients" in claims[1]["text"]
    assert PROMPT_VERSION == "relay-phase3-v3"
