import copy
import json
from dataclasses import replace

import httpx
import pytest

from relay.orchestrator import ResearchAssistant


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
