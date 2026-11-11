"""Lightweight asynchronous load harness for the mock model service.

It drives the FastAPI app through httpx's ASGI transport, so experiments are
offline and reproducible.  The harness measures streaming TTFT and total
latency, records queue wait from response headers, and emits the exact CSV
columns required by Phase 4.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .mock.config import MockConfig
from .mock.service import create_app
from .reliability import AttemptResult, RequestManager, RetryPolicy

CSV_COLUMNS = [
    "request_id",
    "scenario",
    "source",
    "start_time",
    "first_token_ms",
    "total_ms",
    "status",
    "retries",
    "tokens_in",
    "tokens_out",
    "retrieval_setting",
    "answer_grade",
]
ALLOWED_SOURCES = {"real", "stand-in"}
ALLOWED_STATUSES = {"ok", "rate_limited", "timeout", "error"}
ALLOWED_ANSWER_GRADES = {"correct", "wrong", "refused_correctly", "refused_wrongly"}


@dataclass
class RequestRow:
    request_id: str
    scenario: str
    source: str
    start_time: str
    first_token_ms: float | None
    total_ms: float | None
    status: str
    retries: int
    tokens_in: int | None
    tokens_out: int | None
    retrieval_setting: str = ""
    answer_grade: str = ""

    def csv_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "scenario": self.scenario,
            "source": self.source,
            "start_time": self.start_time,
            "first_token_ms": _number(self.first_token_ms),
            "total_ms": _number(self.total_ms),
            "status": self.status,
            "retries": self.retries,
            "tokens_in": "" if self.tokens_in is None else self.tokens_in,
            "tokens_out": "" if self.tokens_out is None else self.tokens_out,
            "retrieval_setting": self.retrieval_setting,
            "answer_grade": self.answer_grade,
        }


@dataclass
class ScenarioResult:
    summary: dict[str, Any]
    rows: list[RequestRow] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("retry-after", "nan"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _usage(data: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = data.get("usage") or {}
    extension = data.get("x_groq") or {}
    usage = usage or extension.get("usage") or {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return (
        prompt if type(prompt) is int and prompt >= 0 else None,
        completion if type(completion) is int and completion >= 0 else None,
    )


def _error_code(data: Any) -> str | None:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            return code if isinstance(code, str) else None
    return None


async def _call_mock(
    client: httpx.AsyncClient,
    *,
    model: str,
    stream: bool,
    client_timeout: float,
) -> AttemptResult:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Phase 4 deterministic load request."}],
        "stream": stream,
        "temperature": 0,
        "max_completion_tokens": 32,
    }
    started = time.perf_counter()
    try:
        if not stream:
            response = await client.post("/v1/chat/completions", json=body, timeout=client_timeout)
            total_ms = (time.perf_counter() - started) * 1000.0
            data = response.json()
            queue_ms = _float_header(response.headers.get("x-mock-queue-ms"))
            prompt, completion = _usage(data)
            status = _http_status(response.status_code, _error_code(data))
            retryable = _retryable(status, _error_code(data))
            return AttemptResult(
                status,
                retryable=retryable,
                retry_after_seconds=_retry_after(response),
                error_code=_error_code(data),
                value={
                    "first_token_ms": None,
                    "total_ms": total_ms,
                    "tokens_in": prompt,
                    "tokens_out": completion,
                    "queue_wait_ms": queue_ms,
                    "http_status": response.status_code,
                },
            )
        first_token_ms: float | None = None
        prompt: int | None = None
        completion: int | None = None
        queue_ms: float | None = None
        saw_done = False
        async with client.stream(
            "POST", "/v1/chat/completions", json=body, timeout=client_timeout
        ) as response:
            queue_ms = _float_header(response.headers.get("x-mock-queue-ms"))
            if response.status_code != 200:
                raw = await response.aread()
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    data = {}
                code = _error_code(data)
                status = _http_status(response.status_code, code)
                return AttemptResult(
                    status,
                    retryable=_retryable(status, code),
                    retry_after_seconds=_retry_after(response),
                    error_code=code,
                    value={
                        "first_token_ms": None,
                        "total_ms": (time.perf_counter() - started) * 1000.0,
                        "tokens_in": None,
                        "tokens_out": None,
                        "queue_wait_ms": queue_ms,
                        "http_status": response.status_code,
                    },
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    saw_done = True
                    break
                try:
                    data = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                for choice in data.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text and first_token_ms is None:
                        first_token_ms = (time.perf_counter() - started) * 1000.0
                prompt_now, completion_now = _usage(data)
                prompt = prompt if prompt_now is None else prompt_now
                completion = completion if completion_now is None else completion_now
        total_ms = (time.perf_counter() - started) * 1000.0
        if not saw_done:
            return AttemptResult(
                "error",
                retryable=False,
                error_code="incomplete_stream",
                value={
                    "first_token_ms": first_token_ms,
                    "total_ms": total_ms,
                    "tokens_in": prompt,
                    "tokens_out": completion,
                    "queue_wait_ms": queue_ms,
                    "http_status": 200,
                },
            )
        return AttemptResult(
            "ok",
            value={
                "first_token_ms": first_token_ms,
                "total_ms": total_ms,
                "tokens_in": prompt,
                "tokens_out": completion,
                "queue_wait_ms": queue_ms,
                "http_status": 200,
            },
        )
    except httpx.TimeoutException:
        return AttemptResult(
            "timeout",
            retryable=True,
            error_code="client_timeout",
            value={
                "first_token_ms": None,
                "total_ms": (time.perf_counter() - started) * 1000.0,
                "tokens_in": None,
                "tokens_out": None,
                "queue_wait_ms": None,
                "http_status": None,
            },
        )
    except Exception as exc:  # noqa: BLE001 - transport failures are data, not crashes
        return AttemptResult(
            "error",
            retryable=False,
            error_code=type(exc).__name__,
            value={
                "first_token_ms": None,
                "total_ms": (time.perf_counter() - started) * 1000.0,
                "tokens_in": None,
                "tokens_out": None,
                "queue_wait_ms": None,
                "http_status": None,
            },
        )


def _float_header(value: str | None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _http_status(http_status: int, error_code: str | None) -> str:
    if http_status == 200:
        return "ok"
    if http_status == 429:
        return "rate_limited"
    if http_status in {408, 504} or error_code == "queue_timeout":
        return "timeout"
    return "error"


def _retryable(status: str, error_code: str | None) -> bool:
    if status == "ok":
        return False
    if status == "rate_limited":
        return error_code != "daily_budget_exhausted"
    if status == "timeout":
        return True
    if error_code in {"queue_full", "client_timeout"}:
        return False
    return error_code == "service_unavailable"


async def run_load_scenario(
    *,
    name: str,
    config: MockConfig,
    requests: int,
    rate_per_second: float | None = None,
    retry_policy: RetryPolicy | None = None,
    manager_max_concurrency: int = 4,
    manager_max_queue_size: int = 8,
    manager_queue_timeout_seconds: float = 1.0,
    client_timeout: float = 10.0,
    stream: bool = True,
    source: str = "stand-in",
) -> ScenarioResult:
    app = create_app(config)
    policy = retry_policy or RetryPolicy()
    manager = RequestManager(
        max_concurrency=manager_max_concurrency,
        max_queue_size=manager_max_queue_size,
        queue_timeout_seconds=manager_queue_timeout_seconds,
        retry_policy=policy,
    )
    transport = httpx.ASGITransport(app=app)
    rows: list[RequestRow] = []
    raw: list[dict[str, Any]] = []
    started = time.perf_counter()

    async with httpx.AsyncClient(transport=transport, base_url="http://mock.local") as client:

        async def one(index: int) -> None:
            row_start = datetime.now(UTC)
            request_id = f"{source}-{name}-{index:04d}"

            async def operation() -> AttemptResult:
                return await _call_mock(
                    client, model=config.model, stream=stream, client_timeout=client_timeout
                )

            result = await manager.execute(operation)
            value = result.value or {}
            manager_queue_ms = result.queue_wait_ms
            server_queue_ms = value.get("queue_wait_ms") or 0.0
            combined_queue_ms = manager_queue_ms + server_queue_ms
            row = RequestRow(
                request_id=request_id,
                scenario=name,
                source=source,
                start_time=row_start.isoformat(),
                first_token_ms=value.get("first_token_ms"),
                total_ms=result.wall_seconds * 1000.0,
                status=result.status,
                retries=result.retries,
                tokens_in=value.get("tokens_in"),
                tokens_out=value.get("tokens_out"),
            )
            rows.append(row)
            raw.append(
                {
                    **row.csv_dict(),
                    "error_code": result.error_code,
                    "attempts": result.attempts,
                    "queue_wait_ms": round(combined_queue_ms, 3),
                    "manager_queue_wait_ms": round(manager_queue_ms, 3),
                    "server_queue_wait_ms": round(server_queue_ms, 3),
                    "retry_delays_seconds": result.retry_delays_seconds,
                    "attempt_log": [
                        {
                            "attempt": log.attempt,
                            "status": log.status,
                            "error_code": log.error_code,
                            "queue_wait_ms": round(log.queue_wait_ms, 3),
                            "retry_delay_seconds": log.retry_delay_seconds,
                        }
                        for log in result.attempt_log
                    ],
                }
            )

        tasks = []
        for index in range(1, requests + 1):
            if rate_per_second is None:
                delay = 0.0
            else:
                delay = (index - 1) / rate_per_second
            tasks.append(asyncio.create_task(_delayed(delay, one, index)))
        await asyncio.gather(*tasks)

    wall_seconds = time.perf_counter() - started
    rows.sort(key=lambda row: row.request_id)
    raw.sort(key=lambda item: str(item["request_id"]))
    summary = _summarize(name, source, rows, raw, wall_seconds, config, policy, manager)
    return ScenarioResult(summary, rows, raw)


async def _delayed(delay: float, function: Any, index: int) -> None:
    if delay > 0:
        await asyncio.sleep(delay)
    await function(index)


def _summarize(
    name: str,
    source: str,
    rows: list[RequestRow],
    raw: list[dict[str, Any]],
    wall_seconds: float,
    config: MockConfig,
    policy: RetryPolicy,
    manager: RequestManager,
) -> dict[str, Any]:
    statuses = {status: 0 for status in sorted(ALLOWED_STATUSES)}
    for row in rows:
        statuses[row.status] = statuses.get(row.status, 0) + 1
    ttft = [row.first_token_ms for row in rows if row.first_token_ms is not None]
    totals = [row.total_ms for row in rows if row.total_ms is not None]
    queue_waits = [item["queue_wait_ms"] for item in raw if item.get("queue_wait_ms") is not None]
    return {
        "scenario": name,
        "source": source,
        "simulated": source == "stand-in",
        "requests": len(rows),
        "ok": statuses.get("ok", 0),
        "rate_limited": statuses.get("rate_limited", 0),
        "timeouts": statuses.get("timeout", 0),
        "errors": statuses.get("error", 0),
        "given_up": sum(1 for row in rows if row.status != "ok"),
        "retries": sum(row.retries for row in rows),
        "tokens_in": sum(row.tokens_in or 0 for row in rows),
        "tokens_out": sum(row.tokens_out or 0 for row in rows),
        "ttft_ms": {
            "p50": percentile(ttft, 0.50),
            "p95": percentile(ttft, 0.95),
            "p99": percentile(ttft, 0.99),
            "samples": len(ttft),
        },
        "total_ms": {
            "p50": percentile(totals, 0.50),
            "p95": percentile(totals, 0.95),
            "p99": percentile(totals, 0.99),
            "samples": len(totals),
        },
        "queue_wait_ms": {
            "p50": percentile(queue_waits, 0.50),
            "p95": percentile(queue_waits, 0.95),
            "p99": percentile(queue_waits, 0.99),
            "samples": len(queue_waits),
        },
        "throughput_rps": round(len(rows) / wall_seconds, 3) if wall_seconds > 0 else None,
        "wall_seconds": round(wall_seconds, 3),
        "retry_policy": {
            "max_attempts": policy.max_attempts,
            "base_delay_seconds": policy.base_delay_seconds,
            "max_delay_seconds": policy.max_delay_seconds,
            "jitter_fraction": policy.jitter_fraction,
            "respect_retry_after": policy.respect_retry_after,
        },
        "manager": {
            "max_concurrency": manager.gate.max_concurrency,
            "max_queue_size": manager.gate.max_queue_size,
            "queue_timeout_seconds": manager.gate.queue_timeout_seconds,
            "stats": manager.snapshot(),
        },
        "mock_config": config.to_dict(),
    }


def validate_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        missing = [column for column in CSV_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"row is missing columns: {missing}")
        if set(row) != set(CSV_COLUMNS):
            raise ValueError("row contains columns outside the required schema")
        if row["source"] not in ALLOWED_SOURCES:
            raise ValueError(f"invalid source: {row['source']}")
        if row["status"] not in ALLOWED_STATUSES:
            raise ValueError(f"invalid status: {row['status']}")
        if row["answer_grade"] not in ALLOWED_ANSWER_GRADES | {""}:
            raise ValueError(f"invalid answer_grade: {row['answer_grade']}")


def write_results_csv(rows: list[RequestRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dictionaries = [row.csv_dict() for row in rows]
    validate_rows(dictionaries)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(dictionaries)


def write_jsonl(items: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True, sort_keys=True) + "\n")


def read_results_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError(f"CSV header mismatch: {reader.fieldnames}")
        rows = [dict(row) for row in reader]
    validate_rows(rows)
    return rows
