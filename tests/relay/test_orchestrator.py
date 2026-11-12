import copy
import json
from dataclasses import replace

import httpx
import pytest

from relay.orchestrator import ResearchAssistant
from retrieval.catalog import PAPERS
from retrieval.models import SourceSpan


def responses(payloads, tool_message, claim, *, finish="stop"):
    plan = httpx.Response(200, json=payloads.completion(tool_message, reason="tool_calls"))
    body = payloads.sse(
        [
            payloads.chunk(json.dumps(claim) + '\n{"type":"done"}\n'),
            payloads.chunk(reason=finish, usage=True),
        ]
    )
    return [plan, httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})]


def test_supported_question_calls_actual_tool_interface_then_streams_validated_answer(
    config, api, api_payloads, tool_message, claim, research_tool
):
    mock = api(responses(api_payloads, tool_message, claim))
    assistant = ResearchAssistant(config, mock.service, research_tool)
    shown = []
    result = assistant.ask("What is the practical latency of Moshi?", shown.append)
    assert result.status == "answered", result.error
    assert "200 ms" in result.answer and shown
    assert result.metrics.tool_calls == 1
    assert result.metrics.input_tokens == 60 and result.metrics.output_tokens == 80
    assert result.metrics.first_answer_token_seconds is not None
    assert result.metrics.citation_validation_seconds >= 0
    assert result.failure_diagnostics is None
    assert len(result.stages) >= 6
    assert mock.received[0]["tool_choice"] == "required"
    assert mock.received[1]["tool_choice"] == "none"
    messages = mock.received[1]["messages"]
    assert messages[2]["tool_calls"][0]["id"] == messages[3]["tool_call_id"] == "call-one"
    evidence = json.loads(messages[3]["content"])
    assert evidence["sources"][0]["arxiv_id"] == "2410.00037"
    assert evidence["sources"][0]["version"] == 1 and evidence["sources"][0]["pages"] == [1]
    assert "UNTRUSTED EVIDENCE" in messages[0]["content"]


def test_original_question_constraints_survive_model_query_rewrite(
    config, api, api_payloads, tool_message, research_tool
):
    mock = api(
        [httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))]
    )
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What p95 latency does Moshi measure on iPhone 15 Pro running iOS?"
    )
    assert result.status == "refused" and len(mock.received) == 1
    assert any("p95" in value for value in result.evidence_assessment["missing"])
    assert not result.claims


def test_empty_retrieval_is_a_refusal_but_storage_failure_is_an_error(
    config, api, api_payloads, tool_message, research_tool
):
    def plan():
        return httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))

    research_tool.pipeline.search = lambda *args, **kwargs: []
    mock = api([plan()])
    result = ResearchAssistant(config, mock.service, research_tool).ask("What are quasars?")
    assert result.status == "refused" and not result.sources

    def broken(*args, **kwargs):
        raise RuntimeError("private storage failure")

    research_tool.pipeline.search = broken
    mock = api([plan()])
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "failed" and result.error["code"] == "retrieval_failed"
    assert not result.answer and "private" not in str(result.error)


def test_maximum_calls_checked_before_executing_any_tool(
    config, api, api_payloads, tool_message, research_tool
):
    tool_message["tool_calls"] *= 3
    mock = api(
        [httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))]
    )
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "failed" and result.error["code"] == "tool_limit"
    assert result.metrics.tool_calls == 0


def test_bounded_multiple_calls_keep_protocol_ids_and_deduplicate_evidence(
    config, api, api_payloads, tool_message, claim, research_tool
):
    second = copy.deepcopy(tool_message["tool_calls"][0])
    second["id"] = "call-two"
    tool_message["tool_calls"].append(second)
    mock = api(responses(api_payloads, tool_message, claim))
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "answered" and result.metrics.tool_calls == 2
    assert len(result.sources) == 1
    messages = mock.received[1]["messages"]
    assert [m["tool_call_id"] for m in messages if m["role"] == "tool"] == ["call-one", "call-two"]


def test_truncated_stream_is_never_recorded_as_success(
    config, api, api_payloads, tool_message, claim, research_tool
):
    mock = api(responses(api_payloads, tool_message, claim, finish="length"))
    shown = []
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is Moshi latency?", shown.append
    )
    assert shown and result.displayed_characters > 0
    assert result.status == "failed" and not result.answer and not result.claims
    assert result.error["code"] == "incomplete_stream"


def test_citation_failure_retains_diagnostics_without_exposing_answer(
    config, api, api_payloads, tool_message, claim, research_tool
):
    bad = copy.deepcopy(claim)
    bad["evidence"][0]["quote"] = "This quotation was fabricated."
    plan = httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))
    body = api_payloads.sse(
        [
            api_payloads.chunk(json.dumps(bad) + "\n"),
            api_payloads.chunk(reason="stop", usage=True),
        ]
    )
    mock = api(
        [plan, httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})]
    )
    shown = []
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is Moshi latency?", shown.append
    )
    assert result.status == "failed" and result.error["code"] == "citation_validation"
    assert not result.answer and not result.claims and not shown
    assert result.displayed_characters == 0
    diagnostics = result.failure_diagnostics
    assert diagnostics is not None
    assert diagnostics["rejected_quote"] == "This quotation was fabricated."
    assert diagnostics["source_id"] == "S1"
    assert diagnostics["accepted_claims"] == []
    assert result.to_dict()["failure_diagnostics"] == diagnostics


def test_stream_failure_retains_last_valid_claim_and_unparsed_suffix(
    config, api, api_payloads, tool_message, claim, research_tool
):
    plan = httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))
    body = api_payloads.sse(
        [
            api_payloads.chunk(json.dumps(claim) + "\nThe prose explains the conflict.\n"),
            api_payloads.chunk(reason="stop", usage=True),
        ]
    )
    mock = api(
        [plan, httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})]
    )
    shown = []
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is Moshi latency?", shown.append
    )
    assert result.status == "failed" and result.error["code"] == "stream_format"
    assert shown and result.displayed_characters > 0
    assert not result.answer and not result.claims
    diagnostics = result.failure_diagnostics
    assert diagnostics is not None
    assert "The prose explains the conflict." in diagnostics["stream_suffix"]
    assert diagnostics["last_record"] == claim
    assert diagnostics["accepted_claim_count"] == 1
    assert diagnostics["accepted_claims"][0]["text"] == claim["text"]


def test_missing_completion_marker_fails_even_when_provider_says_stop(
    config, api, api_payloads, tool_message, claim, research_tool
):
    plan = httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))
    body = api_payloads.sse(
        [
            api_payloads.chunk(json.dumps(claim) + "\n"),
            api_payloads.chunk(reason="stop", usage=True),
        ]
    )
    mock = api(
        [plan, httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})]
    )
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "failed" and result.error["code"] == "incomplete_answer"
    assert not result.answer


def test_normal_text_cannot_simulate_a_tool_call(config, api, api_payloads, research_tool):
    payload = api_payloads.completion(
        {"role": "assistant", "content": "search_research_papers(query='Moshi')"}
    )
    mock = api([httpx.Response(200, json=payload)])
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.error["code"] == "missing_tool_call" and result.metrics.tool_calls == 0


def test_llm_failure_does_not_become_an_unsupported_answer(config, api, research_tool):
    mock = api([httpx.Response(429, json={"error": {"message": "sensitive"}})])
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "failed" and result.error["code"] == "rate_limit"
    assert result.metrics.input_tokens is None and not result.answer


def test_help_branches_without_retrieval_or_llm_and_turns_remain_independent(
    config, api, research_tool
):
    mock = api([])
    assistant = ResearchAssistant(config, mock.service, research_tool)
    first, second = assistant.ask("hi"), assistant.ask("help")
    assert first.status == second.status == "help"
    assert first.metrics.input_tokens == second.metrics.output_tokens == 0
    assert not mock.received and not first.sources and not second.sources


def test_tiny_evidence_budget_is_reported_as_budget_failure(
    config, api, api_payloads, tool_message, research_tool
):
    config = replace(config, evidence_tokens=1)
    mock = api(
        [httpx.Response(200, json=api_payloads.completion(tool_message, reason="tool_calls"))],
        config,
    )
    result = ResearchAssistant(config, mock.service, research_tool).ask("What is Moshi latency?")
    assert result.status == "failed" and result.error["code"] == "context_budget"


@pytest.mark.parametrize("question", ["", " " * 5, "x" * 2001, "hello\x1b[2J"])
def test_bad_questions_never_reach_the_api(config, api, research_tool, question):
    mock = api([])
    result = ResearchAssistant(config, mock.service, research_tool).ask(question)
    assert result.status == "failed" and result.error["code"] == "question"
    assert not mock.received


def use_passage(research_tool, source, text, paper_index):
    paper = PAPERS[paper_index]
    hit = replace(
        source.hit,
        text=text,
        paper_title=paper.title,
        arxiv_id=paper.arxiv_id,
        version=paper.version,
        pages=(1,),
        sources=(SourceSpan(1, "Test evidence", 0, len(text)),),
    )
    research_tool.pipeline.search = lambda *args, **kwargs: [hit]


def recorded_stream(payloads, tool_message, claims, tail='{"type":"done"}'):
    plan = httpx.Response(200, json=payloads.completion(tool_message, reason="tool_calls"))
    text = "\n".join(json.dumps(claim) for claim in claims) + "\n" + tail
    body = payloads.sse([payloads.chunk(text), payloads.chunk(reason="stop", usage=True)])
    return [plan, httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})]


@pytest.mark.parametrize("duplicates", [1, 2])
def test_a9_original_question_coverage_survives_query_rewrite(
    config, api, api_payloads, tool_message, research_tool, source, duplicates
):
    quote = "bt = 1{pt ≥0.5}; p1 = 1.0 by definition, ensuring the first boundary."
    use_passage(research_tool, source, quote, 2)
    claim = {
        "type": "claim",
        "evidence": [{"source_id": "S1", "quote": quote}],
        "text": "The routing threshold is 0.5.",
    }
    mock = api(recorded_stream(api_payloads, tool_message, [claim] * duplicates))
    shown = []
    question = (
        "What probability threshold turns H-Net routing scores into chunk boundaries, "
        "and what boundary probability is forced at the first position?"
    )
    result = ResearchAssistant(config, mock.service, research_tool).ask(question, shown.append)
    assert result.status == "failed" and result.error["code"] == "incomplete_answer"
    assert shown and not result.answer and not result.claims
    assert result.answer_coverage["missing"] == ("first-position boundary probability",)
    assert result.failure_diagnostics["answer_coverage"] == result.answer_coverage
    assert result.failure_diagnostics["accepted_claim_count"] == duplicates
    assert len(mock.received) == 2  # No repair request or retry.
    assert mock.received[1]["messages"][1]["content"] == question


def test_one_claim_can_complete_both_requested_parts(
    config, api, api_payloads, tool_message, research_tool, source
):
    quote = "bt = 1{pt ≥0.5}; p1 = 1.0 by definition, ensuring the first boundary."
    use_passage(research_tool, source, quote, 2)
    claim = {
        "type": "claim",
        "evidence": [{"source_id": "S1", "quote": quote}],
        "text": "The routing threshold is 0.5; the initial boundary probability is 1.0.",
    }
    mock = api(recorded_stream(api_payloads, tool_message, [claim]))
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is H-Net's routing threshold and first-position boundary probability?"
    )
    assert result.status == "answered", result.error
    assert len(result.claims) == 1 and len(result.answer_coverage["required"]) == 2
    assert result.answer_coverage["status"] == "complete"
    assert result.failure_diagnostics is None


def test_unknown_multipart_wording_is_not_automatically_complete(
    config, api, api_payloads, tool_message, claim, research_tool
):
    mock = api(recorded_stream(api_payloads, tool_message, [claim]))
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is Moshi's practical latency, and who designed its training curriculum?"
    )
    assert result.status == "failed" and result.error["code"] == "incomplete_answer"
    assert result.answer_coverage["status"] == "unrecognized"
    assert result.answer_coverage["unrecognized"]
    assert not result.answer and not result.claims


def test_multipart_refusal_does_not_require_inventing_missing_parts(
    config, api, api_payloads, tool_message, research_tool
):
    mock = api(recorded_stream(api_payloads, tool_message, [{"type": "refusal"}]))
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What is Moshi's practical latency and training cost?"
    )
    assert result.status == "refused" and not result.claims
    assert result.answer_coverage is None


def test_a4_numeric_failure_keeps_partial_output_out_of_final_answer(
    config, api, api_payloads, tool_message, research_tool, source
):
    quote = "Transformer (big) | 28.4 | 41.8"
    use_passage(research_tool, source, "BLEU scores:\n" + quote, 0)
    good = {
        "type": "claim",
        "evidence": [{"source_id": "S1", "quote": quote}],
        "text": "Transformer (big) reports 28.4 for English-to-German.",
    }
    bad = copy.deepcopy(good)
    bad["text"] = "The prose reports 41.0 for English-to-French."
    mock = api(recorded_stream(api_payloads, tool_message, [good, bad]))
    shown = []
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "What BLEU scores does Transformer (big) report for English-to-German "
        "and English-to-French?",
        shown.append,
    )
    assert result.status == "failed" and result.error["code"] == "unsupported_number"
    assert len(shown) == 1 and not result.answer and not result.claims
    assert result.failure_diagnostics["unsupported_numbers"] == ["41.0"]
    assert result.failure_diagnostics["accepted_claims"][0]["text"] == good["text"]


@pytest.mark.parametrize("tail, status", [('{"type":"done"}', "answered"), ("\\", "failed")])
def test_a12_formula_stream_completion_is_required(
    config, api, api_payloads, tool_message, research_tool, source, tail, status
):
    quote = r"We scale scores by 1/\sqrt{d_k} to avoid tiny gradients."
    use_passage(research_tool, source, quote, 0)
    claim = {
        "type": "claim",
        "evidence": [{"source_id": "S1", "quote": quote}],
        "text": r"Scaling by 1/\sqrt{d_k} avoids tiny gradients.",
    }
    mock = api(recorded_stream(api_payloads, tool_message, [claim], tail))
    result = ResearchAssistant(config, mock.service, research_tool).ask(
        "Why does scaled dot-product attention divide by the square root of the key dimension?"
    )
    assert result.status == status, result.error
    if status == "failed":
        assert result.error["code"] == "stream_format"
        assert not result.answer and not result.claims
        assert result.failure_diagnostics["stream_suffix"] == "\\"
    else:
        assert r"1/\sqrt{d_k}" in result.answer
