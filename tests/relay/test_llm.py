import time
from dataclasses import replace

import httpx
import pytest

from relay.errors import RelayError


def test_normal_completion_metadata_usage_and_no_reasoning(api, api_payloads):
    payload = api_payloads.completion(
        {"role": "assistant", "content": "OK", "reasoning": "private reasoning"}
    )
    mock = api([httpx.Response(200, json=payload)])
    reply = mock.service.complete([{"role": "user", "content": "A test."}])
    assert reply.message == {"role": "assistant", "content": "OK"}
    assert (
        reply.request.input_tokens,
        reply.request.output_tokens,
        reply.request.total_tokens,
    ) == (20, 30, 50)
    assert reply.request.request_id == "req-test"
    assert reply.request.provider_model == reply.request.model == "openai/gpt-oss-20b"
    assert reply.request.status == "completed" and reply.request.duration_seconds >= 0
    assert mock.received[0]["include_reasoning"] is False
    assert mock.received[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "authentication", False),
        (400, "invalid_request", False),
        (429, "rate_limit", True),
        (503, "provider_error", True),
    ],
)
def test_api_errors_are_sanitized_and_never_automatically_retried(api, status, code, retryable):
    mock = api(
        [
            httpx.Response(
                status,
                json={"error": {"message": "secret-key-and-prompt"}},
                headers={"retry-after": "2"},
            )
        ]
    )
    with pytest.raises(RelayError) as failure:
        mock.service.complete([{"role": "user", "content": "Test"}])
    assert failure.value.code == code and failure.value.retryable == retryable
    assert "secret" not in str(failure.value)
    assert failure.value.retry_after_seconds == 2
    assert len(mock.received) == 1 and mock.service.records[0].status == "failed"
    assert mock.service.records[0].input_tokens is None


def test_stream_tracks_usage_from_groq_extension_and_first_content_token(api, api_payloads):
    body = api_payloads.sse(
        [api_payloads.chunk("hello "), api_payloads.chunk("world", reason="stop", usage=True)]
    )
    mock = api([httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})])
    parts = []
    record = mock.service.stream([{"role": "user", "content": "Test"}], parts.append)
    assert parts == ["hello ", "world"]
    assert record.status == "completed" and record.first_token_seconds is not None
    assert record.input_tokens == 40 and record.output_tokens == 50
    assert record.request_id == "req-stream"


def test_missing_stream_terminator_is_not_success(api, api_payloads):
    body = api_payloads.sse([api_payloads.chunk("partial")])
    mock = api([httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})])
    parts = []
    with pytest.raises(RelayError, match="did not finish"):
        mock.service.stream([{"role": "user", "content": "Test"}], parts.append)
    assert parts == ["partial"] and mock.service.records[-1].status == "failed"
    assert mock.service.records[-1].input_tokens is None


def test_stream_transport_failure_keeps_partial_usage_unknown(api, api_payloads):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield (
                "data: " + __import__("json").dumps(api_payloads.chunk("partial")) + "\n\n"
            ).encode()
            raise httpx.ReadError("private request body")

    mock = api(
        [httpx.Response(200, stream=Broken(), headers={"content-type": "text/event-stream"})]
    )
    with pytest.raises(RelayError) as error:
        mock.service.stream([{"role": "user", "content": "Test"}], lambda text: None)
    assert error.value.code == "connection"
    assert "private" not in str(error.value)
    assert mock.service.records[-1].status == "failed"


def test_deadline_and_prompt_limit_prevent_requests(api, config):
    mock = api([], replace(config, prompt_token_budget=20))
    with pytest.raises(RelayError) as error:
        mock.service.complete([{"role": "user", "content": "Test"}])
    assert error.value.code == "context_budget" and not mock.received
    with pytest.raises(RelayError) as error:
        mock.service.complete([], deadline=time.perf_counter() - 1)
    assert error.value.code == "timeout" and not mock.received


def test_cancellation_closes_stream_and_is_not_success(api, api_payloads):
    body = api_payloads.sse([api_payloads.chunk("part"), api_payloads.chunk(reason="stop")])
    mock = api([httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})])

    def interrupt(text):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        mock.service.stream([{"role": "user", "content": "Test"}], interrupt)
    assert mock.service.records[-1].status == "cancelled"


def test_generation_cannot_execute_an_additional_tool(api, api_payloads):
    item = api_payloads.chunk()
    item["choices"][0]["delta"] = {
        "tool_calls": [
            {
                "index": 0,
                "id": "extra",
                "type": "function",
                "function": {"name": "search_research_papers", "arguments": "{}"},
            }
        ]
    }
    mock = api(
        [
            httpx.Response(
                200, text=api_payloads.sse([item]), headers={"content-type": "text/event-stream"}
            )
        ]
    )
    with pytest.raises(RelayError) as error:
        mock.service.stream([{"role": "user", "content": "Test"}], lambda _: None)
    assert error.value.code == "unexpected_tool_call"
