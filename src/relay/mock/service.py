"""Deterministic local HTTP stand-in for the Groq chat-completions surface.

The service never imports or calls Groq.  It returns OpenAI/Groq-shaped JSON and
SSE chunks so the same client-side code can exercise success, failure, timeout,
rate-limit, budget and overload paths reproducibly.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .accounting import RequestAccounting
from .config import MockConfig, estimate_tokens, scenario_config
from .gate import BoundedGate, QueueRejected

SIMULATED_HEADER = {"x-mock-simulated": "true"}


def _error(
    status: int,
    code: str,
    message: str,
    *,
    error_type: str = "server_error",
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    merged = {**SIMULATED_HEADER, **(headers or {})}
    return JSONResponse(
        status_code=status,
        headers=merged,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


def _split_answer(text: str, chunks: int) -> list[str]:
    count = max(1, min(chunks, len(text)))
    size = math.ceil(len(text) / count)
    parts = [text[index : index + size] for index in range(0, len(text), size)]
    return [part for part in parts if part] or [text]


class MockModel:
    def __init__(self, config: MockConfig | None = None) -> None:
        self.config = config or MockConfig.from_env()
        self.accounting = RequestAccounting(
            per_minute_limit=self.config.per_minute_limit,
            daily_request_budget=self.config.daily_request_budget,
            daily_token_budget=self.config.daily_token_budget,
        )
        self.gate = BoundedGate(
            self.config.max_concurrency,
            self.config.max_queue_size,
            self.config.queue_timeout_ms / 1000.0,
        )

    def scenario(self, request: Request) -> MockConfig:
        requested = request.headers.get("x-mock-scenario")
        if not requested or requested == self.config.scenario:
            return self.config
        return scenario_config(requested)

    def _input_tokens(self, payload: dict[str, Any]) -> int:
        total = self.config.input_token_overhead
        for message in payload.get("messages") or []:
            content = message.get("content", "") if isinstance(message, dict) else ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, sort_keys=True)
            total += estimate_tokens(content) + 4
        tools = payload.get("tools")
        if tools:
            total += estimate_tokens(json.dumps(tools, ensure_ascii=False, sort_keys=True))
        return max(1, total)

    def _should_fail(self, sequence: int) -> bool:
        if sequence in self.config.failure_on_requests:
            return True
        if self.config.failure_every and sequence % self.config.failure_every == 0:
            return True
        if self.config.failure_probability > 0:
            mixed = (sequence * 1_103_515_245 + self.config.seed * 12_345 + 0x9E3779B9) & 0xFFFFFFFF
            return (mixed % 10_000) / 10_000 < self.config.failure_probability
        return False

    def _delay_seconds(self, config: MockConfig) -> float:
        active = max(1, self.gate.stats.active)
        extra = self.config.load_latency_ms_per_active * (active - 1)
        return (config.processing_delay_ms + extra) / 1000.0

    def _completion(
        self,
        sequence: int,
        input_tokens: int,
        output_tokens: int,
        answer: str,
        finish_reason: str = "stop",
    ) -> dict[str, Any]:
        return {
            "id": f"mockcmpl-{sequence:08d}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.config.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            "x_groq": {"id": f"mockreq-{sequence:08d}"},
        }

    async def handle(self, request: Request) -> JSONResponse | StreamingResponse:
        try:
            payload = await request.json()
        except Exception:
            self.accounting.record_error()
            return _error(400, "invalid_json", "The request body is not valid JSON.")
        if not isinstance(payload, dict):
            self.accounting.record_error()
            return _error(400, "invalid_request", "The request body must be a JSON object.")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self.accounting.record_error()
            return _error(400, "invalid_request", "messages must be a nonempty array.")
        stream = payload.get("stream", False)
        if not isinstance(stream, bool):
            self.accounting.record_error()
            return _error(400, "invalid_request", "stream must be a boolean.")

        config = self.scenario(request)
        input_tokens = self._input_tokens(payload)
        admission = self.accounting.admit(
            input_tokens,
            per_minute_limit=config.per_minute_limit,
            daily_request_budget=config.daily_request_budget,
            daily_token_budget=config.daily_token_budget,
        )
        headers = {
            **SIMULATED_HEADER,
            "x-mock-scenario": config.scenario,
            **admission.headers(),
        }
        if not admission.allowed:
            if admission.reason == "rate_limit_exceeded":
                return _error(
                    429,
                    "rate_limit_exceeded",
                    "Simulated per-minute request limit reached.",
                    error_type="rate_limit_error",
                    headers=headers,
                )
            return _error(
                429,
                "daily_budget_exhausted",
                "Simulated daily request/token budget is exhausted.",
                error_type="rate_limit_error",
                headers=headers,
            )

        try:
            queue_wait = await self.gate.acquire()
        except QueueRejected as exc:
            headers["x-mock-queue-ms"] = f"{exc.waited_seconds * 1000.0:.1f}"
            if exc.reason == "queue_timeout":
                self.accounting.record_timeout()
                return _error(
                    504,
                    "queue_timeout",
                    "Simulated request queue wait exceeded its timeout.",
                    error_type="timeout_error",
                    headers=headers,
                )
            self.accounting.record_overloaded()
            return _error(
                503,
                "queue_full",
                "Simulated bounded request queue is full.",
                headers=headers,
            )

        headers["x-mock-queue-ms"] = f"{queue_wait * 1000.0:.1f}"
        headers["x-mock-active"] = str(self.gate.stats.active)
        delay = self._delay_seconds(config)

        if config.scenario == "timeout":
            try:
                await asyncio.sleep(config.timeout_after_ms / 1000.0)
                self.accounting.record_timeout()
                return _error(
                    504,
                    "timeout",
                    "Simulated upstream model timeout.",
                    error_type="timeout_error",
                    headers=headers,
                )
            finally:
                await self.gate.release()

        if self._should_fail(admission.sequence):
            try:
                await asyncio.sleep(min(delay, 0.05))
                self.accounting.record_error()
                return _error(
                    self.config.failure_status,
                    "service_unavailable",
                    "Simulated temporary model-service failure.",
                    headers={**headers, "retry-after": f"{self.config.retry_after_seconds:g}"},
                )
            finally:
                await self.gate.release()

        output_tokens = estimate_tokens(self.config.answer_text)
        answer = self.config.answer_text
        if stream:
            return self._streaming_response(
                admission.sequence,
                input_tokens,
                output_tokens,
                answer,
                delay,
                config,
                headers,
            )

        try:
            await asyncio.sleep(delay)
        finally:
            await self.gate.release()
        self.accounting.record_ok(output_tokens)
        headers["x-mock-input-tokens"] = str(input_tokens)
        headers["x-mock-output-tokens"] = str(output_tokens)
        return JSONResponse(
            self._completion(admission.sequence, input_tokens, output_tokens, answer),
            headers=headers,
        )

    def _streaming_response(
        self,
        sequence: int,
        input_tokens: int,
        output_tokens: int,
        answer: str,
        delay: float,
        config: MockConfig,
        headers: dict[str, str],
    ) -> StreamingResponse:
        parts = _split_answer(answer, config.streaming_chunks)

        async def events() -> AsyncIterator[str]:
            nonlocal headers
            try:
                await asyncio.sleep(delay)
                for index, part in enumerate(parts):
                    if index:
                        await asyncio.sleep(config.streaming_chunk_delay_ms / 1000.0)
                    chunk = {
                        "id": f"mockcmpl-{sequence:08d}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": self.config.model,
                        "choices": [
                            {"index": 0, "delta": {"content": part}, "finish_reason": None}
                        ],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=True)}\n\n"
                final = {
                    "id": f"mockcmpl-{sequence:08d}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.config.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                    "x_groq": {
                        "id": f"mockreq-{sequence:08d}",
                        "usage": {
                            "prompt_tokens": input_tokens,
                            "completion_tokens": output_tokens,
                            "total_tokens": input_tokens + output_tokens,
                        },
                    },
                }
                yield f"data: {json.dumps(final, ensure_ascii=True)}\n\n"
                yield "data: [DONE]\n\n"
                self.accounting.record_ok(output_tokens)
            finally:
                await self.gate.release()

        headers = {
            **headers,
            "cache-control": "no-cache",
            "x-mock-input-tokens": str(input_tokens),
            "x-mock-output-tokens": str(output_tokens),
        }
        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


def create_app(config: MockConfig | None = None) -> FastAPI:
    model = MockModel(config)
    app = FastAPI(title="The Relay mock model service", version="phase4")
    app.state.mock = model

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "simulated": True,
            "scenario": model.config.scenario,
            "generated_utc": datetime.now(UTC).isoformat(),
        }

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        return {
            "simulated": True,
            "notice": "All timings and token counts are simulated, except when copied "
            "explicitly from real Groq calibration files.",
            "scenario": model.config.scenario,
            "config": model.config.to_dict(),
            "accounting": model.accounting.snapshot().to_dict(),
            "queue": model.gate.snapshot(),
        }

    @app.post("/admin/reset")
    async def reset() -> dict[str, Any]:
        model.accounting.reset()
        return {"status": "reset", "simulated": True}

    @app.post("/v1/chat/completions", response_model=None)
    async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
        return await model.handle(request)

    return app


app = create_app()
