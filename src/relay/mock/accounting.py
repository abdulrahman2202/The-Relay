"""Request, per-minute and daily accounting for the mock model service."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str | None
    sequence: int
    minute_used: int
    minute_limit: int | None
    daily_requests_used: int
    daily_request_budget: int | None
    daily_tokens_used: int
    daily_token_budget: int | None
    retry_after_seconds: float

    def headers(self) -> dict[str, str]:
        headers = {
            "x-mock-minute-used": str(self.minute_used),
            "x-mock-daily-requests-used": str(self.daily_requests_used),
            "x-mock-daily-tokens-used": str(self.daily_tokens_used),
        }
        if self.minute_limit is not None:
            headers["x-ratelimit-limit-requests"] = str(self.minute_limit)
            headers["x-ratelimit-remaining-requests"] = str(
                max(0, self.minute_limit - self.minute_used)
            )
        if self.daily_request_budget is not None:
            headers["x-mock-daily-request-remaining"] = str(
                max(0, self.daily_request_budget - self.daily_requests_used)
            )
        if not self.allowed and self.retry_after_seconds > 0:
            headers["retry-after"] = f"{self.retry_after_seconds:g}"
        return headers


@dataclass
class AccountingSnapshot:
    total_requests: int
    admitted: int
    ok: int
    rate_limited: int
    budget_rejected: int
    timeouts: int
    errors: int
    overloaded: int
    tokens_in: int
    tokens_out: int
    daily_requests: int
    daily_tokens: int
    minute_used: int
    per_minute_limit: int | None
    daily_request_budget: int | None
    daily_token_budget: int | None
    day: str

    def to_dict(self) -> dict[str, int | str | None]:
        return self.__dict__.copy()


@dataclass
class RequestAccounting:
    per_minute_limit: int | None = 120
    daily_request_budget: int | None = 5000
    daily_token_budget: int | None = 2_000_000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _minute_window: deque[float] = field(default_factory=deque, repr=False)
    _day: date = field(default_factory=lambda: datetime.now(UTC).date(), repr=False)
    _daily_requests: int = 0
    _daily_tokens: int = 0
    _sequence: int = 0
    _total_requests: int = 0
    _admitted: int = 0
    _ok: int = 0
    _rate_limited: int = 0
    _budget_rejected: int = 0
    _timeouts: int = 0
    _errors: int = 0
    _overloaded: int = 0
    _tokens_in: int = 0
    _tokens_out: int = 0

    def reset(self) -> None:
        with self._lock:
            self._minute_window.clear()
            self._day = datetime.now(UTC).date()
            self._daily_requests = 0
            self._daily_tokens = 0
            self._sequence = 0
            self._total_requests = 0
            self._admitted = 0
            self._ok = 0
            self._rate_limited = 0
            self._budget_rejected = 0
            self._timeouts = 0
            self._errors = 0
            self._overloaded = 0
            self._tokens_in = 0
            self._tokens_out = 0

    def _roll(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day = today
            self._daily_requests = 0
            self._daily_tokens = 0
        now = time.monotonic()
        while self._minute_window and now - self._minute_window[0] >= 60.0:
            self._minute_window.popleft()

    def admit(
        self,
        input_tokens: int,
        *,
        per_minute_limit: int | None = None,
        daily_request_budget: int | None = None,
        daily_token_budget: int | None = None,
    ) -> Admission:
        minute_limit = self.per_minute_limit if per_minute_limit is None else per_minute_limit
        request_budget = (
            self.daily_request_budget if daily_request_budget is None else daily_request_budget
        )
        token_budget = self.daily_token_budget if daily_token_budget is None else daily_token_budget
        with self._lock:
            self._roll()
            self._total_requests += 1
            used = len(self._minute_window)
            if (request_budget is not None and self._daily_requests >= request_budget) or (
                token_budget is not None
                and self._daily_tokens + max(0, input_tokens) > token_budget
            ):
                self._budget_rejected += 1
                return Admission(
                    False,
                    "daily_budget_exhausted",
                    self._sequence,
                    used,
                    minute_limit,
                    self._daily_requests,
                    request_budget,
                    self._daily_tokens,
                    token_budget,
                    60.0,
                )
            if minute_limit is not None and used >= minute_limit:
                self._rate_limited += 1
                retry_after = 60.0
                if self._minute_window:
                    retry_after = max(0.0, 60.0 - (time.monotonic() - self._minute_window[0]))
                return Admission(
                    False,
                    "rate_limit_exceeded",
                    self._sequence,
                    used,
                    minute_limit,
                    self._daily_requests,
                    request_budget,
                    self._daily_tokens,
                    token_budget,
                    round(retry_after, 3),
                )
            self._sequence += 1
            self._admitted += 1
            self._daily_requests += 1
            self._daily_tokens += max(0, input_tokens)
            self._tokens_in += max(0, input_tokens)
            self._minute_window.append(time.monotonic())
            return Admission(
                True,
                None,
                self._sequence,
                used + 1,
                minute_limit,
                self._daily_requests,
                request_budget,
                self._daily_tokens,
                token_budget,
                0.0,
            )

    def record_ok(self, output_tokens: int) -> None:
        with self._lock:
            self._ok += 1
            self._tokens_out += max(0, output_tokens)
            self._daily_tokens += max(0, output_tokens)

    def record_rate_limited(self) -> None:
        with self._lock:
            self._rate_limited += 1

    def record_budget_rejected(self) -> None:
        with self._lock:
            self._budget_rejected += 1

    def record_timeout(self) -> None:
        with self._lock:
            self._timeouts += 1

    def record_error(self) -> None:
        with self._lock:
            self._errors += 1

    def record_overloaded(self) -> None:
        with self._lock:
            self._overloaded += 1

    def snapshot(self) -> AccountingSnapshot:
        with self._lock:
            self._roll()
            return AccountingSnapshot(
                total_requests=self._total_requests,
                admitted=self._admitted,
                ok=self._ok,
                rate_limited=self._rate_limited,
                budget_rejected=self._budget_rejected,
                timeouts=self._timeouts,
                errors=self._errors,
                overloaded=self._overloaded,
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                daily_requests=self._daily_requests,
                daily_tokens=self._daily_tokens,
                minute_used=len(self._minute_window),
                per_minute_limit=self.per_minute_limit,
                daily_request_budget=self.daily_request_budget,
                daily_token_budget=self.daily_token_budget,
                day=self._day.isoformat(),
            )

    @property
    def sequence(self) -> int:
        with self._lock:
            return self._sequence
