import json
import re
import socket
from types import SimpleNamespace

import groq
import httpx
import pytest

from relay.config import RelayConfig
from relay.llm import GroqService
from relay.tools import EvidenceSource
from retrieval.catalog import PAPERS
from retrieval.models import SearchHit, SourceSpan


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Automated Phase 3 tests must not contact a service")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def config():
    return RelayConfig()


def completion(message, *, reason="stop", usage=True):
    payload = {
        "id": "completion-test",
        "object": "chat.completion",
        "created": 1,
        "model": "openai/gpt-oss-20b",
        "choices": [{"index": 0, "finish_reason": reason, "message": message}],
        "x_groq": {"id": "req-test"},
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}
    return payload


def chunk(text=None, *, reason=None, usage=False):
    payload = {
        "id": "stream-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "openai/gpt-oss-20b",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": reason}],
    }
    if usage:
        payload["x_groq"] = {
            "id": "req-stream",
            "usage": {"prompt_tokens": 40, "completion_tokens": 50, "total_tokens": 90},
        }
    return payload


def sse(chunks):
    return "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"


@pytest.fixture
def api():
    clients = []

    def factory(responses, cfg=None):
        received = []
        queue = iter(responses)

        def handler(request):
            received.append(json.loads(request.content))
            response = next(queue)
            if isinstance(response, Exception):
                raise response
            return response

        client = groq.Groq(
            api_key="test-only-key",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        return SimpleNamespace(
            service=GroqService(cfg or RelayConfig(), client=client), received=received
        )

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def source():
    paper = PAPERS[1]
    text = "Moshi has a theoretical latency of 160ms, 200ms in practice."
    hit = SearchHit(
        "chunk-moshi",
        text,
        paper.title,
        paper.arxiv_id,
        paper.version,
        (1,),
        ("Abstract",),
        (SourceSpan(1, "Abstract", 0, len(text)),),
        0.1,
        char_start=100,
    )
    return EvidenceSource("S1", hit, "call-one")


@pytest.fixture
def api_payloads():
    return SimpleNamespace(completion=completion, chunk=chunk, sse=sse)


@pytest.fixture
def tool_message():
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call-one",
                "type": "function",
                "function": {
                    "name": "search_research_papers",
                    "arguments": json.dumps(
                        {
                            "query": "Moshi theoretical practical latency",
                            "strategy": "bm25",
                            "preset": 600,
                        }
                    ),
                },
            }
        ],
    }


@pytest.fixture
def claim(source):
    return {
        "type": "claim",
        "text": "Moshi's practical latency is 200 ms.",
        "evidence": [{"source_id": "S1", "quote": source.hit.text}],
    }


@pytest.fixture
def word_tokenizer():
    # Only a plumbing fixture; real MiniLM tokenization remains in tests/rag.
    return SimpleNamespace(encode=lambda text, **kwargs: re.findall(r"\w+|[^\w\s]", text))


@pytest.fixture
def research_tool(config, source, word_tokenizer):
    from relay.tools import ResearchTool

    pipeline = SimpleNamespace(
        search=lambda *args, **kwargs: [source.hit],
        embedder=SimpleNamespace(tokenizer=word_tokenizer),
    )
    return ResearchTool(config, pipeline=pipeline)
