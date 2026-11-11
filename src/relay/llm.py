"""Small synchronous Groq adapter with bounded calls and sanitized failures."""

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import groq
import httpx

from .budget import prompt_upper_bound
from .config import RelayConfig
from .errors import RelayError


@dataclass
class RequestRecord:
    stage: str
    model: str
    streaming: bool
    started_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "in_progress"
    provider_model: str | None = None
    request_id: str | None = None
    completion_id: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    duration_seconds: float = 0.0
    first_token_seconds: float | None = None
    prompt_budget_upper_bound: int = 0
    max_output_tokens: int = 0
    timeout_seconds: float = 0.0
    temperature: float = 0.0
    seed: int = 0
    tool_names: list[str] = field(default_factory=list)
    error_code: str | None = None


@dataclass(frozen=True)
class Completion:
    message: dict[str, Any]
    request: RequestRecord


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[\w./:-]{1,160}", value) else None


def _record_response(record: RequestRecord, response: Any) -> None:
    record.provider_model = _identifier(getattr(response, "model", None)) or record.provider_model
    record.completion_id = _identifier(getattr(response, "id", None)) or record.completion_id
    extension = getattr(response, "x_groq", None)
    request_id = getattr(extension, "id", None) or getattr(response, "_request_id", None)
    record.request_id = _identifier(request_id) or record.request_id
    usage = getattr(response, "usage", None) or getattr(extension, "usage", None)
    if usage is not None:
        for destination, name in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            value = getattr(usage, name, None)
            if type(value) is int and value >= 0:
                setattr(record, destination, value)
    if getattr(extension, "error", None):
        raise RelayError("stream_failed", "Groq reported an incomplete stream.", retryable=True)


def _safe_error(error: Exception) -> RelayError:
    if isinstance(error, RelayError):
        return error
    if isinstance(error, (groq.APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return RelayError("timeout", "The Groq request timed out.", retryable=True)
    if isinstance(error, groq.APIStatusError):
        status = error.status_code
        retry_after = None
        try:
            value = float(error.response.headers.get("retry-after", "nan"))
            if math.isfinite(value) and 0 <= value <= 3600:
                retry_after = value
        except (TypeError, ValueError):
            pass
        descriptions = {
            400: ("invalid_request", "Groq rejected the request or model capability."),
            401: ("authentication", "Groq rejected the API key. Check GROQ_API_KEY."),
            403: ("permission", "The Groq account cannot access this operation."),
            404: ("model_unavailable", "The configured Groq model or endpoint is unavailable."),
            429: ("rate_limit", "Groq rate limit reached. Wait before trying again."),
        }
        code, message = descriptions.get(
            status, ("provider_error", "Groq could not complete the request.")
        )
        return RelayError(
            code,
            message,
            retryable=status in {408, 409, 429} or status >= 500,
            status_code=status,
            retry_after_seconds=retry_after,
        )
    if isinstance(error, (groq.APIConnectionError, httpx.TransportError)):
        return RelayError("connection", "Cannot connect to Groq.", retryable=True)
    return RelayError("provider_protocol", "The model response could not be processed safely.")


class GroqService:
    def __init__(
        self,
        config: RelayConfig,
        *,
        api_key: str | None = None,
        client: Any = None,
        request_limit: int | None = None,
    ) -> None:
        if client is None and not api_key:
            raise RelayError("configuration", "A GROQ_API_KEY is required.")
        self.config = config
        self.client = (
            client
            if client is not None
            else groq.Groq(
                api_key=api_key,
                base_url="https://api.groq.com",
                timeout=config.request_timeout,
                max_retries=0,
            )
        )
        self.request_limit = request_limit
        self.calls = 0
        self.records: list[RequestRecord] = []

    def close(self) -> None:
        self.client.close()

    def _parameters(
        self,
        messages: list[dict[str, Any]],
        *,
        stage: str,
        streaming: bool,
        tools: list[dict[str, Any]] | None,
        tool_choice: str | None,
        deadline: float | None,
    ) -> tuple[dict[str, Any], RequestRecord]:
        if self.request_limit is not None and self.calls >= self.request_limit:
            raise RelayError("request_limit", "The configured request limit has been reached.")
        remaining = (
            self.config.request_timeout
            if deadline is None
            else min(self.config.request_timeout, deadline - time.perf_counter())
        )
        if remaining <= 0:
            raise RelayError("timeout", "The question deadline has expired.")
        bound = prompt_upper_bound(messages, tools)
        if bound > self.config.prompt_token_budget:
            raise RelayError("context_budget", "The request exceeds the configured prompt budget.")
        record = RequestRecord(stage, self.config.model, streaming, prompt_budget_upper_bound=bound)
        record.max_output_tokens = (
            self.config.planning_tokens if stage == "planning" else self.config.max_output_tokens
        )
        record.timeout_seconds = remaining
        self.records.append(record)
        self.calls += 1
        parameters: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0,
            "seed": 0,
            "stream": streaming,
            "max_completion_tokens": self.config.planning_tokens
            if stage == "planning"
            else self.config.max_output_tokens,
            "timeout": remaining,
        }
        if tools:
            parameters.update(
                tools=tools, tool_choice=tool_choice or "auto", parallel_tool_calls=False
            )
        if self.config.model.startswith("openai/gpt-oss-"):
            parameters.update(reasoning_effort="low", include_reasoning=False)
        return parameters, record

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        stage: str = "completion",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        deadline: float | None = None,
    ) -> Completion:
        parameters, record = self._parameters(
            messages,
            stage=stage,
            streaming=False,
            tools=tools,
            tool_choice=tool_choice,
            deadline=deadline,
        )
        start = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**parameters)
            _record_response(record, response)
            if len(response.choices) != 1:
                raise RelayError("provider_protocol", "Expected exactly one model response.")
            choice = response.choices[0]
            record.finish_reason = choice.finish_reason
            if choice.finish_reason not in {"stop", "tool_calls"}:
                raise RelayError("incomplete_completion", "Groq did not finish the response.")
            # Do not forward or persist hidden reasoning, debug token IDs or provider annotations.
            message = choice.message.model_dump(
                include={"role", "content", "tool_calls"}, exclude_none=True
            )
            record.tool_names = [c["function"]["name"] for c in message.get("tool_calls", [])]
            record.status = "completed"
            return Completion(message, record)
        except KeyboardInterrupt:
            record.status, record.error_code = "cancelled", "interrupted"
            raise
        except Exception as exc:
            error = _safe_error(exc)
            record.status, record.error_code = "failed", error.code
            raise error from None
        finally:
            record.duration_seconds = time.perf_counter() - start

    def stream(
        self,
        messages: list[dict[str, Any]],
        on_delta: Callable[[str], None],
        *,
        tools: list[dict[str, Any]] | None = None,
        deadline: float | None = None,
    ) -> RequestRecord:
        parameters, record = self._parameters(
            messages,
            stage="generation",
            streaming=True,
            tools=tools,
            tool_choice="none",
            deadline=deadline,
        )
        start = time.perf_counter()
        end_by = min(deadline or math.inf, start + self.config.request_timeout)
        stream = None
        characters = 0
        try:
            stream = self.client.chat.completions.create(**parameters)
            for index, chunk in enumerate(stream):
                if time.perf_counter() > end_by or index >= 20000:
                    raise RelayError("timeout", "The Groq stream exceeded its execution limit.")
                _record_response(record, chunk)
                if len(chunk.choices) > 1:
                    raise RelayError("provider_protocol", "Unexpected multiple stream choices.")
                for choice in chunk.choices:
                    if choice.delta.tool_calls:
                        raise RelayError(
                            "unexpected_tool_call",
                            "Tool execution is disabled during answer generation.",
                        )
                    text = choice.delta.content or ""
                    if text:
                        if record.finish_reason is not None:
                            raise RelayError(
                                "provider_protocol", "Unexpected content after stream termination."
                            )
                        if record.first_token_seconds is None:
                            record.first_token_seconds = time.perf_counter() - start
                        characters += len(text)
                        if characters > self.config.max_stream_chars:
                            raise RelayError(
                                "stream_limit", "The response exceeded the configured size limit."
                            )
                        on_delta(text)
                    if choice.finish_reason is not None:
                        record.finish_reason = choice.finish_reason
            if record.finish_reason != "stop":
                raise RelayError(
                    "incomplete_stream", "The answer stream did not finish successfully."
                )
            record.status = "completed"
            return record
        except KeyboardInterrupt:
            record.status, record.error_code = "cancelled", "interrupted"
            raise
        except Exception as exc:
            error = _safe_error(exc)
            record.status, record.error_code = "failed", error.code
            raise error from None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    # Closing must not turn an interrupted/failed request into a successful one.
                    if record.status == "completed":
                        record.status, record.error_code = "failed", "stream_close"
                        record.duration_seconds = time.perf_counter() - start
                        raise RelayError(
                            "stream_close", "The response stream did not close successfully."
                        ) from None
            record.duration_seconds = time.perf_counter() - start
