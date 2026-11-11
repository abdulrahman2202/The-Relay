import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from relay.errors import RelayError
from relay.tools import ResearchTool, parse_tool_calls, tool_schema


def test_real_interface_schema_and_arguments(config, tool_message):
    schema = tool_schema(config)
    assert schema["type"] == "function"
    assert schema["function"]["parameters"]["required"] == ["query"]
    assert schema["function"]["parameters"]["additionalProperties"] is False
    call = parse_tool_calls(tool_message, config)[0]
    assert (call.call_id, call.strategy, call.preset) == ("call-one", "bm25", 600)
    assert call.message() == tool_message["tool_calls"][0]


@pytest.mark.parametrize(
    "arguments",
    [
        '{"query":"Moshi latency"}',
        '{"query":"Moshi latency","strategy":"bm25"}',
        '{"query":"Moshi latency","preset":600}',
    ],
)
def test_omitted_optional_arguments_use_configured_defaults(config, tool_message, arguments):
    tool_message["tool_calls"][0]["function"]["arguments"] = arguments
    call = parse_tool_calls(tool_message, config)[0]
    assert (call.query, call.strategy, call.preset) == ("Moshi latency", "bm25", 600)
    assert json.loads(call.message()["function"]["arguments"]) == {
        "query": "Moshi latency",
        "strategy": "bm25",
        "preset": 600,
    }


@pytest.mark.parametrize(
    "arguments",
    [
        "[]",
        '{"query":"x","query":"y","strategy":"bm25","preset":600}',
        '{"query":"x","strategy":"bm25","preset":true}',
        '{"query":"x","strategy":"bm25","preset":900}',
        '{"query":"x","strategy":"vector","preset":600}',
        '{"query":"x","strategy":"bm25","preset":600,"command":"rm"}',
        '{"query":"","strategy":"bm25","preset":600}',
        '{"query":"x","strategy":"bm25","preset":NaN}',
    ],
)
def test_untrusted_tool_arguments_are_rejected(config, tool_message, arguments):
    tool_message["tool_calls"][0]["function"]["arguments"] = arguments
    with pytest.raises(RelayError):
        parse_tool_calls(tool_message, config)


def test_unknown_duplicate_and_excessive_calls_are_rejected(config, tool_message):
    malicious = copy.deepcopy(tool_message)
    malicious["tool_calls"][0]["function"]["name"] = "run_shell"
    with pytest.raises(RelayError, match="unavailable"):
        parse_tool_calls(malicious, config)
    with pytest.raises(RelayError, match="repeated"):
        parse_tool_calls({"tool_calls": tool_message["tool_calls"] * 2}, config)
    with pytest.raises(RelayError, match="allowed number"):
        parse_tool_calls({"tool_calls": tool_message["tool_calls"] * 3}, config)


def test_tool_returns_cited_rag_passages_and_sanitizes_failure(config, source, tool_message):
    calls = []

    def search(query, **options):
        calls.append((query, options))
        return [source.hit]

    tool = ResearchTool(config, pipeline=SimpleNamespace(search=search))
    call = parse_tool_calls(tool_message, config)[0]
    output = tool.execute(call)
    assert output.hits == (source.hit,) and output.error is None
    assert calls[0][1] == {"strategy": "bm25"}

    def failure(*args, **kwargs):
        raise RuntimeError("private-path-or-key")

    tool.pipeline.search = failure
    failed = tool.execute(call)
    assert failed.error.code == "retrieval_failed" and not failed.hits
    assert "private" not in str(failed.error)


def test_wrong_paper_version_cannot_enter_evidence(config, source, tool_message):
    tool = ResearchTool(
        config, pipeline=SimpleNamespace(search=lambda *a, **k: [replace(source.hit, version=99)])
    )
    output = tool.execute(parse_tool_calls(tool_message, config)[0])
    assert output.error is not None and not output.hits
