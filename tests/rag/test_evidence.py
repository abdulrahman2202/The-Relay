import pytest

from retrieval.evidence import EvidenceRequirement, assess_evidence, infer_requirements
from retrieval.models import SearchHit, SourceSpan


def passage(text, paper="2410.00037"):
    return SearchHit(
        paper, text, "Paper", paper, 1, (1,), (), (SourceSpan(1, None, 0, len(text)),), 0.01
    )


def test_numbers_from_another_model_do_not_satisfy_the_request():
    hits = [passage("MMLU accuracy is 60%.")]
    requirements = infer_requirements("What MMLU accuracy does Attention Is All You Need report?")
    assert assess_evidence(hits, requirements).refused


def test_training_data_size_is_not_model_parameter_count():
    question = "What benchmark results are reported for a 70-billion-parameter H-Net?"
    requirements = infer_requirements(question)
    assert assess_evidence(
        [passage("70B Total Training Bytes", "2507.07955")], requirements
    ).refused
    supported = passage("The 70B-parameter H-Net reports benchmark results.", "2507.07955")
    assert not assess_evidence([supported], requirements).refused


def test_generic_latency_does_not_satisfy_hardware_percentile_constraints():
    requirements = infer_requirements(
        "What p95 latency does Moshi measure on iPhone 15 Pro running iOS?"
    )
    result = assess_evidence(
        [passage("Moshi has 160ms theoretical latency, 200ms in practice.")], requirements
    )
    assert result.refused
    assert any("p95" in label for label in result.missing)


def test_explicit_requirements_check_all_units_with_literal_alternatives():
    requirements = (
        EvidenceRequirement("theoretical latency", ("160 ms", "160 milliseconds"), "2410.00037"),
        EvidenceRequirement("practical latency", ("200 ms",), "2410.00037"),
    )
    assert assess_evidence([passage("160ms theoretical latency")], requirements).refused
    result = assess_evidence(
        [passage("160 milliseconds theoretical, 200ms practical.")], requirements
    )
    assert result.status == "candidate_evidence"
    assert not result.refused


def test_no_hits_and_dated_pricing_are_insufficient():
    assert assess_evidence([], ()).refused
    requirements = infer_requirements("What is Moshi API pricing in November 2026?")
    assert assess_evidence([passage("Moshi provides a streaming API.")], requirements).refused


@pytest.mark.parametrize(
    "settings",
    [
        {"label": "empty"},
        {"label": "blank", "alternatives": ("",)},
        {"label": "paper", "arxiv_id": "0000.00000"},
    ],
)
def test_invalid_requirements(settings):
    with pytest.raises(ValueError):
        EvidenceRequirement(**settings)
