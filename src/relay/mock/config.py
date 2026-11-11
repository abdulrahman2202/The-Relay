"""Configuration for the deterministic local mock model service.

The mock service is calibrated from real Groq observations but is not the real
service.  Every scenario is explicit so an experiment can be reproduced without
network access, and no credential or provider call is required.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, replace
from typing import Any

SCENARIOS = (
    "normal",
    "slow",
    "temporary_failure",
    "rate_limit",
    "budget_exhausted",
    "timeout",
    "streaming",
    "overloaded",
)


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate for simulated usage metadata.

    This is a byte/character heuristic, not a tokenizer.  It is labeled as
    simulated usage everywhere it is reported.
    """
    if not isinstance(text, str):
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class MockConfig:
    scenario: str = "normal"
    seed: int = 0
    model: str = "mock/gpt-oss-20b"
    per_minute_limit: int | None = 120
    daily_request_budget: int | None = 5000
    daily_token_budget: int | None = 2_000_000
    processing_delay_ms: int = 650
    slow_delay_ms: int = 2500
    timeout_after_ms: int = 300
    failure_status: int = 503
    failure_probability: float = 0.0
    failure_on_requests: tuple[int, ...] = ()
    failure_every: int | None = None
    retry_after_seconds: float = 1.0
    max_concurrency: int = 4
    max_queue_size: int = 8
    queue_timeout_ms: int = 1000
    load_latency_ms_per_active: int = 80
    streaming_chunks: int = 4
    streaming_chunk_delay_ms: int = 20
    answer_text: str = "Simulated deterministic answer from the Relay mock model service."
    input_token_overhead: int = 56

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        if not isinstance(self.model, str) or not self.model:
            raise ValueError("model must be a nonempty string")
        for name in (
            "per_minute_limit",
            "daily_request_budget",
            "daily_token_budget",
            "failure_every",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.failure_every is not None and self.failure_every < 1:
            raise ValueError("failure_every must be at least 1")
        for name in (
            "processing_delay_ms",
            "slow_delay_ms",
            "timeout_after_ms",
            "max_concurrency",
            "streaming_chunks",
            "input_token_overhead",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "max_queue_size",
            "queue_timeout_ms",
            "load_latency_ms_per_active",
            "streaming_chunk_delay_ms",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.failure_status not in {500, 502, 503, 504}:
            raise ValueError("failure_status must be a retryable 5xx status")
        if not isinstance(self.failure_probability, (int, float)) or not (
            0.0 <= float(self.failure_probability) <= 1.0
        ):
            raise ValueError("failure_probability must be between 0 and 1")
        if not math.isfinite(float(self.retry_after_seconds)) or self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be a nonnegative finite number")
        if not isinstance(self.failure_on_requests, tuple) or any(
            type(value) is not int or value < 1 for value in self.failure_on_requests
        ):
            raise ValueError("failure_on_requests must contain positive integers")
        if len(set(self.failure_on_requests)) != len(self.failure_on_requests):
            raise ValueError("failure_on_requests must not contain duplicates")
        if not isinstance(self.answer_text, str) or not 1 <= len(self.answer_text) <= 4000:
            raise ValueError("answer_text must be 1-4000 characters")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_env(cls, **overrides: Any) -> MockConfig:
        values: dict[str, Any] = {}
        scenario = os.environ.get("MOCK_SCENARIO")
        if scenario:
            values["scenario"] = scenario
        return replace(cls(**values), **overrides)


def scenario_config(scenario: str, **overrides: Any) -> MockConfig:
    """Return an explicit, reproducible preset for one named scenario."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}")
    base = MockConfig(scenario=scenario)
    changes: dict[str, Any] = {}
    if scenario == "slow":
        changes["processing_delay_ms"] = base.slow_delay_ms
    elif scenario == "temporary_failure":
        changes["failure_every"] = 3
    elif scenario == "rate_limit":
        changes["per_minute_limit"] = 10
    elif scenario == "budget_exhausted":
        changes["daily_request_budget"] = 0
    elif scenario == "timeout":
        changes["timeout_after_ms"] = 300
    elif scenario == "streaming":
        changes["streaming_chunks"] = 5
        changes["streaming_chunk_delay_ms"] = 40
    elif scenario == "overloaded":
        changes["max_concurrency"] = 1
        changes["max_queue_size"] = 2
        changes["queue_timeout_ms"] = 300
        changes["load_latency_ms_per_active"] = 250
    changes.update(overrides)
    return replace(base, **changes)
