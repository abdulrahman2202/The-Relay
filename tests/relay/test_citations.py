import copy
import json
from dataclasses import replace

import pytest

from relay.citations import ClaimStream, validate_claim
from relay.errors import RelayError
from retrieval.models import SourceSpan


def test_valid_citation_uses_authoritative_metadata_and_quote_offsets(source, claim):
    background = "Background on a different physical page.\n\n"
    hit = replace(
        source.hit,
        text=background + source.hit.text,
        pages=(1, 2),
        sources=(
            SourceSpan(1, "Background", 0, len(background)),
            SourceSpan(2, "Latency", len(background), len(background) + len(source.hit.text)),
        ),
    )
    result = validate_claim(claim, {"S1": replace(source, hit=hit)})
    citation = result.citations[0]
    assert citation.pages == (2,) and citation.source_url.endswith("#page=2")
    assert citation.char_start == 100 + len(background)
    assert "arXiv:2410.00037v1, p. 2" in citation.label


@pytest.mark.parametrize(
    "mutation", ["source", "quote", "number", "missing", "control", "freeform"]
)
def test_invalid_claims_are_rejected(source, claim, mutation):
    if mutation == "source":
        claim["evidence"][0]["source_id"] = "S999"
    elif mutation == "quote":
        claim["evidence"][0]["quote"] = "This quotation was fabricated."
    elif mutation == "number":
        claim["text"] = "Moshi latency is 900 ms."
    elif mutation == "missing":
        claim["evidence"] = []
    elif mutation == "control":
        claim["text"] += "\x1b[2J"
    else:
        claim["text"] += " [S77]"
    with pytest.raises(RelayError):
        validate_claim(claim, {"S1": source})


def test_stream_publishes_only_complete_validated_claims(source, claim):
    output = []
    parser = ClaimStream([source], output.append)
    line = json.dumps(claim)
    parser.feed(line[:40])
    assert not output
    parser.feed(line[40:] + '\n{"type":"done"}\n')
    parser.finish()
    assert len(output) == 1 and "200 ms" in output[0] and "[S1]" in output[0]
    assert parser.validation_seconds >= 0


def test_stream_accepts_adjacent_objects_without_newline_separator(source, claim):
    output = []
    parser = ClaimStream([source], output.append)
    payload = json.dumps(claim) + '{"type":"done"}'
    for character in payload:
        parser.feed(character)
    parser.finish()
    assert parser.done and len(parser.claims) == 1 and len(output) == 1
    assert "[S1]" in output[0]


def test_stream_handles_braces_and_escaped_quotes_inside_strings(source, claim):
    claim["text"] = 'Moshi uses a {braced} note and the quote "200 ms" in its text.'
    output = []
    parser = ClaimStream([source], output.append)
    parser.feed(json.dumps(claim) + '{"type":"done"}')
    parser.finish()
    assert parser.done and len(output) == 1


def test_stream_rejects_incomplete_record_at_end(source, claim):
    parser = ClaimStream([source], lambda text: None)
    parser.feed(json.dumps(claim) + '{"type":"do')
    with pytest.raises(RelayError, match="incomplete record"):
        parser.finish()


def test_failure_after_valid_claim_does_not_emit_invalid_claim(source, claim):
    output = []
    parser = ClaimStream([source], output.append)
    parser.feed(json.dumps(claim) + "\n")
    bad = copy.deepcopy(claim)
    bad["evidence"][0]["source_id"] = "S99"
    with pytest.raises(RelayError):
        parser.feed(json.dumps(bad) + "\n")
    assert len(output) == 1
    with pytest.raises(RelayError, match="completion marker"):
        parser.finish()


@pytest.mark.parametrize(
    "body",
    [
        '{"type":"done"}',
        '{"type":"refusal"}\n{"type":"claim","text":"x","evidence":[]}',
        '{"type":"refusal"}\n{"type":"done"}\n{"type":"refusal"}',
    ],
)
def test_empty_mixed_and_post_termination_outputs_fail(source, body):
    parser = ClaimStream([source], lambda text: None)
    with pytest.raises(RelayError):
        parser.feed(body + "\n")


def test_model_refusal_does_not_accept_arbitrary_text(source):
    output = []
    parser = ClaimStream([source], output.append)
    parser.feed('{"type":"refusal"}\n{"type":"done"}')
    parser.finish()
    assert parser.refused and not parser.claims
    assert output == [
        "The supplied papers do not provide enough evidence to answer that question.\n"
    ]
