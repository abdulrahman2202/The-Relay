"""Bounded asynchronous admission gate used by the mock service.

This is intentionally small: a semaphore with a bounded waiting room and a
queue timeout.  It prevents unbounded queue growth without pretending to be a
distributed job queue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


class QueueRejected(Exception):
    def __init__(self, reason: str, waited_seconds: float = 0.0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.waited_seconds = max(0.0, waited_seconds)


@dataclass
class GateStats:
    active: int = 0
    waiting: int = 0
    admitted: int = 0
    queue_full: int = 0
    queue_timeouts: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "active": self.active,
            "waiting": self.waiting,
            "admitted": self.admitted,
            "queue_full": self.queue_full,
            "queue_timeouts": self.queue_timeouts,
        }


class BoundedGate:
    def __init__(
        self,
        max_concurrency: int,
        max_queue_size: int,
        queue_timeout_seconds: float,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if max_queue_size < 0:
            raise ValueError("max_queue_size must be nonnegative")
        if queue_timeout_seconds < 0:
            raise ValueError("queue_timeout_seconds must be nonnegative")
        self.max_concurrency = max_concurrency
        self.max_queue_size = max_queue_size
        self.queue_timeout_seconds = queue_timeout_seconds
        self._condition = asyncio.Condition()
        self.stats = GateStats()

    async def acquire(self) -> float:
        """Return queue wait in seconds, or raise QueueRejected."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        async with self._condition:
            if self.stats.active < self.max_concurrency:
                self.stats.active += 1
                self.stats.admitted += 1
                return 0.0
            if self.stats.waiting >= self.max_queue_size:
                self.stats.queue_full += 1
                raise QueueRejected("queue_full")
            self.stats.waiting += 1
            try:
                while self.stats.active >= self.max_concurrency:
                    remaining = self.queue_timeout_seconds - (loop.time() - start)
                    if remaining <= 0:
                        self.stats.queue_timeouts += 1
                        raise QueueRejected("queue_timeout", loop.time() - start)
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                    except TimeoutError:
                        self.stats.queue_timeouts += 1
                        raise QueueRejected("queue_timeout", loop.time() - start) from None
                self.stats.active += 1
                self.stats.admitted += 1
                return loop.time() - start
            finally:
                self.stats.waiting -= 1

    async def release(self) -> None:
        async with self._condition:
            if self.stats.active > 0:
                self.stats.active -= 1
            self._condition.notify(1)

    def snapshot(self) -> dict[str, int]:
        return self.stats.to_dict()
