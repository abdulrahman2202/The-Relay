import copy
import json
from dataclasses import replace

import pytest

from relay.citations import ClaimStream, validate_claim
from relay.errors import RelayError
from relay.tools import EvidenceSource
from retrieval.models import SourceSpan


def evidence(source, text, *, source_id="S1"):
    hit = replace(
        source.hit,
        text=text,
        pages=(1,),
        sources=(SourceSpan(1, "Test", 0, len(text)),),
        char_start=0,
    )
    return EvidenceSource(source_id, hit, "call-one")


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


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Adam uses ε = 10^{−9} for numerical stability.", "ε = 10^{-9} for numerical stability"),
        ("The method is contextdependent in the source.", "context-dependent"),
        ("The method is context- dependent in the source.", "context-dependent"),
        (
            "Transformer | 3.62 | T15 | 0.7404 | 0.599",
            "Transformer 3.62 T15 0.7404 0.599",
        ),
        (
            "XWinograd-zh improves from 59.9 → 66.3.",
            "XWinograd-zh improves from 59.9 -> 66.3",
        ),
        (
            "H-Net is 3.6x more data efficient than isotropic model.",
            "3.6× more data efficient than isotropic model",
        ),
        ("We divide each by ^{√}dk, then apply softmax.", "divide each by √dk"),
        ("We scale by 1\n√dk before softmax.", "We scale by 1/√dk before softmax"),
        ("The boundary is bt = 1{pt ≥0.5} for each step.", "bt = 1{pt >=0.5}"),
        ("Transformer (big) | 28.4 | 41.8", "Transformer (big) 28.4 41.8"),
    ],
)
def test_canonical_quote_matching_accepts_documented_formatting(source, text, quote):
    claim = {
        "type": "claim",
        "text": "The passage records the stated evidence.",
        "evidence": [{"source_id": "S1", "quote": quote}],
    }
    result = validate_claim(claim, {"S1": evidence(source, text)})
    assert result.citations[0].source_id == "S1"


def test_canonical_quote_preserves_numeric_support_and_source_offsets(source):
    text = "Adam uses ε = 10^{−9} for numerical stability."
    claim = {
        "type": "claim",
        "text": "Adam uses epsilon 10^-9.",
        "evidence": [{"source_id": "S1", "quote": "ε = 10^{-9} for numerical stability"}],
    }
    result = validate_claim(claim, {"S1": evidence(source, text)})
    assert "10^{−9}" in result.citations[0].quote


def test_canonical_quote_matching_rejects_changed_content(source):
    claim = {
        "type": "claim",
        "text": "The passage records the stated evidence.",
        "evidence": [
            {
                "source_id": "S1",
                "quote": "3.6× more data efficient than transformer model",
            }
        ],
    }
    with pytest.raises(RelayError, match="absent"):
        validate_claim(
            claim,
            {"S1": evidence(source, "H-Net is 3.6x more data efficient than isotropic model.")},
        )


def test_stream_accepts_structured_conflicting_source_values(source):
    table = evidence(source, "Transformer (big) | 28.4 | 41.8", source_id="S1")
    prose = evidence(
        source,
        "our big model achieves a BLEU score of 41.0, outperforming all previously "
        "published single models",
        source_id="S2",
    )
    output = []
    parser = ClaimStream([table, prose], output.append)
    claims = [
        {
            "type": "claim",
            "text": "The table reports 41.8 for English-to-French.",
            "evidence": [{"source_id": "S1", "quote": "Transformer (big) | 28.4 | 41.8"}],
        },
        {
            "type": "claim",
            "text": "The prose reports 41.0 for English-to-French.",
            "evidence": [
                {"source_id": "S2", "quote": "our big model achieves a BLEU score of 41.0"}
            ],
        },
    ]
    for item in claims:
        parser.feed(json.dumps(item) + "\n")
    parser.feed('{"type":"done"}\n')
    parser.finish()
    assert len(parser.claims) == 2 and len(output) == 2


def test_stream_accepts_multiple_claims_for_a_multipart_answer(source):
    text = (
        "bt = 1{pt ≥0.5}\n\nwhere p1 = 1.0 by definition, ensuring the sequence "
        "begins with a boundary"
    )
    parser = ClaimStream([evidence(source, text)], lambda text: None)
    claims = [
        {
            "type": "claim",
            "text": "The routing threshold is 0.5.",
            "evidence": [{"source_id": "S1", "quote": "bt = 1{pt ≥0.5}"}],
        },
        {
            "type": "claim",
            "text": "The first boundary probability is 1.0.",
            "evidence": [
                {
                    "source_id": "S1",
                    "quote": "p1 = 1.0 by definition, ensuring the sequence begins with a boundary",
                }
            ],
        },
    ]
    for item in claims:
        parser.feed(json.dumps(item) + "\n")
    parser.feed('{"type":"done"}\n')
    parser.finish()
    assert len(parser.claims) == 2


def test_stream_diagnostics_capture_rejected_quote_and_source(source, claim):
    parser = ClaimStream([source], lambda text: None)
    bad = copy.deepcopy(claim)
    bad["evidence"][0]["quote"] = "This quotation was fabricated."
    with pytest.raises(RelayError, match="absent"):
        parser.feed(json.dumps(bad) + "\n")
    failure = parser.failure
    assert failure is not None
    assert failure["rejected_quote"] == "This quotation was fabricated."
    assert failure["source_id"] == "S1"
    assert failure["error"]["code"] == "citation_validation"
    assert failure["accepted_claim_count"] == 0
    assert failure["accepted_claims"] == []
    assert failure["candidate_record"] == bad


def test_stream_diagnostics_capture_unparsed_suffix_and_last_record(source, claim):
    parser = ClaimStream([source], lambda text: None)
    parser.feed(json.dumps(claim) + "\n")
    with pytest.raises(RelayError, match="structured answer object"):
        parser.feed("The prose explains the conflict.\n")
    failure = parser.failure
    assert failure is not None
    assert "The prose explains the conflict." in failure["stream_suffix"]
    assert failure["last_record"] == claim
    assert failure["accepted_claim_count"] == 1
    assert failure["accepted_claims"][0]["text"] == claim["text"]


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
