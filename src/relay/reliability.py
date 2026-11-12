"""Small bounded request manager and conservative retry policy.

The manager is intentionally in-process.  It limits concurrent model calls,
bounds the waiting room, applies a queue timeout, and retries only failures
classified as retryable.  It is a reliability helper, not a distributed queue.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .mock.gate import BoundedGate, QueueRejected


def _jitter(attempt: int, seed: int, fraction: float) -> float:
    if fraction <= 0:
        return 0.0
    mixed = (attempt * 2_654_435_761 + seed * 97 + 0x85EBCA6B) & 0xFFFFFFFF
    unit = (mixed % 10_000) / 10_000
    return (unit * 2.0 - 1.0) * fraction


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 2.0
    jitter_fraction: float = 0.1
    respect_retry_after: bool = True
    max_retry_after_seconds: float = 5.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        for name in (
            "base_delay_seconds",
            "max_delay_seconds",
            "jitter_fraction",
            "max_retry_after_seconds",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a nonnegative finite number")
        if self.jitter_fraction > 1:
            raise ValueError("jitter_fraction must be between 0 and 1")

    def delay(self, attempt: int, retry_after_seconds: float | None = None) -> float | None:
        """Return a bounded delay, or None when the server asks for too long a wait."""
        if (
            self.respect_retry_after
            and retry_after_seconds is not None
            and retry_after_seconds > self.max_retry_after_seconds
        ):
            return None
        exponential = self.base_delay_seconds * (2 ** (attempt - 1))
        chosen = exponential
        if (
            self.respect_retry_after
            and retry_after_seconds is not None
            and retry_after_seconds > chosen
        ):
            chosen = retry_after_seconds
        chosen = min(chosen, self.max_delay_seconds)
        delay = max(0.0, chosen * (1.0 + _jitter(attempt, self.seed, self.jitter_fraction)))
        if self.respect_retry_after and retry_after_seconds is not None:
            # The backoff cap and negative jitter must not shorten the server's minimum.
            delay = max(delay, retry_after_seconds)
        return delay


@dataclass
class AttemptResult:
    status: str
    retryable: bool = False
    retry_after_seconds: float | None = None
    error_code: str | None = None
    value: Any = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class AttemptLog:
    attempt: int
    status: str
    error_code: str | None
    queue_wait_ms: float
    retry_delay_seconds: float | None = None


@dataclass
class ManagedResult:
    status: str
    value: Any = None
    error_code: str | None = None
    attempts: int = 0
    retries: int = 0
    queue_wait_ms: float = 0.0
    retry_delays_seconds: list[float] = field(default_factory=list)
    attempt_log: list[AttemptLog] = field(default_factory=list)
    wall_seconds: float = 0.0

    @property
    def given_up(self) -> bool:
        return self.status != "ok"


class RequestManager:
    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        max_queue_size: int = 8,
        queue_timeout_seconds: float = 1.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.gate = BoundedGate(max_concurrency, max_queue_size, queue_timeout_seconds)
        self.policy = retry_policy or RetryPolicy()

    def snapshot(self) -> dict[str, int]:
        return self.gate.snapshot()

    async def _attempt(
        self, operation: Callable[[], Awaitable[AttemptResult]]
    ) -> tuple[AttemptResult, float]:
        try:
            queue_wait = await self.gate.acquire()
        except QueueRejected as exc:
            status = "timeout" if exc.reason == "queue_timeout" else "error"
            return (
                AttemptResult(status, retryable=False, error_code=exc.reason),
                exc.waited_seconds,
            )
        try:
            result = await operation()
            return result, queue_wait
        except TimeoutError:
            return AttemptResult("timeout", retryable=True, error_code="timeout"), queue_wait
        except Exception as exc:  # noqa: BLE001 - classified, never re-raised to callers
            return (
                AttemptResult("error", retryable=False, error_code=type(exc).__name__),
                queue_wait,
            )
        finally:
            await self.gate.release()

    async def execute(self, operation: Callable[[], Awaitable[AttemptResult]]) -> ManagedResult:
        started = time.perf_counter()
        queue_waits: list[float] = []
        retry_delays: list[float] = []
        logs: list[AttemptLog] = []
        retries = 0
        last: AttemptResult | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            last, queue_wait = await self._attempt(operation)
            queue_waits.append(queue_wait)
            log = AttemptLog(attempt, last.status, last.error_code, queue_wait * 1000.0)
            logs.append(log)
            if last.ok:
                return ManagedResult(
                    status="ok",
                    value=last.value,
                    attempts=attempt,
                    retries=retries,
                    queue_wait_ms=sum(queue_waits) * 1000.0,
                    retry_delays_seconds=retry_delays,
                    attempt_log=logs,
                    wall_seconds=time.perf_counter() - started,
                )
            if not last.retryable or attempt >= self.policy.max_attempts:
                break
            delay = self.policy.delay(attempt, last.retry_after_seconds)
            if delay is None:
                break
            log.retry_delay_seconds = delay
            retry_delays.append(delay)
            retries += 1
            await asyncio.sleep(delay)
        assert last is not None
        return ManagedResult(
            status=last.status,
            error_code=last.error_code,
            attempts=len(logs),
            retries=retries,
            queue_wait_ms=sum(queue_waits) * 1000.0,
            retry_delays_seconds=retry_delays,
            attempt_log=logs,
            wall_seconds=time.perf_counter() - started,
        )
