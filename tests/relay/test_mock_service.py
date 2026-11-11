import asyncio
import json
import time

import httpx

from relay.mock.config import MockConfig
from relay.mock.service import create_app


def request(config: MockConfig, body, *, headers=None):
    return requests(config, [body], headers=headers)[0]


def requests(config: MockConfig, bodies, *, headers=None):
    async def run():
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            return [
                await client.post("/v1/chat/completions", json=item, headers=headers or {})
                for item in bodies
            ]

    return asyncio.run(run())


def body(stream=False):
    return {
        "model": "mock/gpt-oss-20b",
        "messages": [{"role": "user", "content": "Test request"}],
        "stream": stream,
    }


def test_normal_completion_has_realistic_metadata_and_simulated_marker():
    response = request(MockConfig(processing_delay_ms=5), body())
    assert response.status_code == 200
    payload = response.json()
    assert response.headers["x-mock-simulated"] == "true"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["choices"][0]["message"]["content"].startswith("Simulated")
    assert payload["usage"]["prompt_tokens"] > 0
    assert payload["usage"]["completion_tokens"] > 0
    assert payload["x_groq"]["id"].startswith("mockreq-")


def test_streaming_returns_incremental_chunks_and_final_usage():
    async def run():
        app = create_app(
            MockConfig(processing_delay_ms=10, streaming_chunks=3, streaming_chunk_delay_ms=5)
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            started = time.perf_counter()
            first = None
            content = []
            usage = None
            done = False
            async with client.stream(
                "POST", "/v1/chat/completions", json=body(stream=True)
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        done = True
                        break
                    item = json.loads(data)
                    for choice in item["choices"]:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            first = first or time.perf_counter() - started
                            content.append(text)
                    if item.get("usage"):
                        usage = item["usage"]
            return "".join(content), first, usage, done

    text, first, usage, done = asyncio.run(run())
    assert text.startswith("Simulated") and done
    assert first is not None and first < 0.5
    assert usage["prompt_tokens"] > 0 and usage["completion_tokens"] > 0


def test_per_minute_rate_limit_is_retryable_and_explained():
    config = MockConfig(per_minute_limit=2, processing_delay_ms=1)
    first, second, third = requests(config, [body(), body(), body()])
    assert first.status_code == second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limit_exceeded"
    assert float(third.headers["retry-after"]) > 0


def test_daily_request_budget_exhaustion_is_distinct():
    config = MockConfig(daily_request_budget=1, processing_delay_ms=1)
    first, second = requests(config, [body(), body()])
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "daily_budget_exhausted"


def test_daily_token_budget_can_reject_before_any_request():
    response = request(MockConfig(daily_token_budget=1, processing_delay_ms=1), body())
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "daily_budget_exhausted"


def test_failure_probability_of_one_is_deterministic_failure():
    config = MockConfig(failure_probability=1.0, processing_delay_ms=1)
    first, second = requests(config, [body(), body()])
    assert first.status_code == second.status_code == 503


def test_concurrent_load_increases_latency():
    config = MockConfig(
        max_concurrency=4,
        max_queue_size=8,
        processing_delay_ms=40,
        load_latency_ms_per_active=120,
    )

    async def run():
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            started = time.perf_counter()
            responses = await asyncio.gather(
                client.post("/v1/chat/completions", json=body()),
                client.post("/v1/chat/completions", json=body()),
            )
            return responses, time.perf_counter() - started

    responses, elapsed = asyncio.run(run())
    assert [response.status_code for response in responses] == [200, 200]
    assert elapsed >= 0.12


def test_deterministic_failure_pattern_and_recovery():
    config = MockConfig(failure_on_requests=(2,), processing_delay_ms=1, retry_after_seconds=1)
    first, second, third = requests(config, [body(), body(), body()])
    assert first.status_code == 200
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "service_unavailable"
    assert second.headers["retry-after"] == "1"
    assert third.status_code == 200


def test_timeout_scenario_returns_504():
    response = request(MockConfig(scenario="timeout", timeout_after_ms=10), body())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


def test_slow_scenario_delays_the_response():
    started = time.perf_counter()
    response = request(
        MockConfig(scenario="slow", slow_delay_ms=80, processing_delay_ms=80), body()
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert elapsed >= 0.07


def test_bounded_queue_rejects_when_full():
    config = MockConfig(
        max_concurrency=1,
        max_queue_size=1,
        queue_timeout_ms=1000,
        processing_delay_ms=150,
    )

    async def run():
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            return await asyncio.gather(
                *[client.post("/v1/chat/completions", json=body()) for _ in range(3)]
            )

    responses = asyncio.run(run())
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 200, 503]
    assert any(
        response.status_code == 503 and response.json()["error"]["code"] == "queue_full"
        for response in responses
    )


def test_bounded_queue_times_out_waiter():
    config = MockConfig(
        max_concurrency=1,
        max_queue_size=2,
        queue_timeout_ms=20,
        processing_delay_ms=150,
    )

    async def run():
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            return await asyncio.gather(
                *[client.post("/v1/chat/completions", json=body()) for _ in range(2)]
            )

    responses = asyncio.run(run())
    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 504]
    assert any(
        response.status_code == 504 and response.json()["error"]["code"] == "queue_timeout"
        for response in responses
    )


def test_metrics_reports_accounting_and_queue_state():
    config = MockConfig(processing_delay_ms=1, per_minute_limit=10)

    async def run():
        app = create_app(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:
            await client.post("/v1/chat/completions", json=body())
            return (await client.get("/metrics")).json()

    metrics = asyncio.run(run())
    assert metrics["simulated"] is True
    assert metrics["accounting"]["ok"] == 1
    assert metrics["accounting"]["total_requests"] == 1
    assert metrics["queue"]["admitted"] == 1
