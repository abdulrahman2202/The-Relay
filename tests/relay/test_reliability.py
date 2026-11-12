import asyncio

import pytest

from relay.reliability import AttemptResult, RequestManager, RetryPolicy


def run(coroutine):
    return asyncio.run(coroutine)


def test_retry_recovers_from_one_temporary_failure():
    outcomes = [
        AttemptResult("error", retryable=True, error_code="service_unavailable", value="bad"),
        AttemptResult("ok", value="recovered"),
    ]

    async def operation():
        return outcomes.pop(0)

    result = run(
        RequestManager(
            retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.001, jitter_fraction=0)
        ).execute(operation)
    )
    assert result.status == "ok" and result.value == "recovered"
    assert result.attempts == 2 and result.retries == 1


def test_daily_budget_failure_is_not_retried():
    calls = []

    async def operation():
        calls.append(1)
        return AttemptResult("rate_limited", retryable=False, error_code="daily_budget_exhausted")

    result = run(
        RequestManager(
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.001, jitter_fraction=0)
        ).execute(operation)
    )
    assert result.status == "rate_limited" and result.retries == 0 and len(calls) == 1
    assert result.error_code == "daily_budget_exhausted"


def test_retry_attempts_are_capped_to_avoid_storms():
    calls = []

    async def operation():
        calls.append(1)
        return AttemptResult("error", retryable=True, error_code="service_unavailable")

    result = run(
        RequestManager(
            retry_policy=RetryPolicy(
                max_attempts=3,
                base_delay_seconds=0.001,
                max_delay_seconds=0.002,
                jitter_fraction=0,
            )
        ).execute(operation)
    )
    assert len(calls) == 3
    assert result.attempts == 3 and result.retries == 2
    assert len(result.retry_delays_seconds) == 2


def test_retry_after_beyond_limit_gives_up_instead_of_sleeping():
    calls = []

    async def operation():
        calls.append(1)
        return AttemptResult(
            "rate_limited", retryable=True, retry_after_seconds=100, error_code="rate_limit"
        )

    result = run(
        RequestManager(
            retry_policy=RetryPolicy(
                max_attempts=3, base_delay_seconds=0.001, max_retry_after_seconds=5
            )
        ).execute(operation)
    )
    assert len(calls) == 1 and result.status == "rate_limited" and result.retries == 0


@pytest.mark.parametrize("retry_after, jitter", [(1.0, 0.1), (4.0, 0.0), (4.0, 0.1)])
def test_retry_after_is_never_shortened_by_delay_cap_or_jitter(retry_after, jitter):
    policy = RetryPolicy(max_delay_seconds=2, max_retry_after_seconds=5, jitter_fraction=jitter)
    assert policy.delay(1, retry_after) >= retry_after


def test_manager_waits_for_server_minimum_before_retry(monkeypatch):
    events = []

    async def sleep(delay):
        events.append(("wait", delay))

    async def operation():
        events.append(("request", None))
        if len(events) == 1:
            return AttemptResult("rate_limited", retryable=True, retry_after_seconds=4)
        return AttemptResult("ok", value="recovered")

    monkeypatch.setattr("relay.reliability.asyncio.sleep", sleep)
    result = run(RequestManager(retry_policy=RetryPolicy(max_attempts=2)).execute(operation))
    assert result.status == "ok" and result.retries == 1
    assert [event[0] for event in events] == ["request", "wait", "request"]
    assert events[1][1] >= 4
    assert result.retry_delays_seconds == [events[1][1]]


def test_explicit_simulated_retry_policy_can_ignore_retry_after():
    policy = RetryPolicy(respect_retry_after=False)
    assert policy.delay(1, 60) == policy.delay(1)


def test_bounded_queue_rejects_when_waiting_room_is_full():
    async def scenario():
        manager = RequestManager(max_concurrency=1, max_queue_size=0)

        async def slow():
            await asyncio.sleep(0.05)
            return AttemptResult("ok", value="done")

        first = asyncio.create_task(manager.execute(slow))
        await asyncio.sleep(0.005)
        second = await manager.execute(slow)
        first_result = await first
        return first_result, second

    first, second = run(scenario())
    assert first.status == "ok"
    assert second.status == "error" and second.error_code == "queue_full"
    assert second.attempts == 1 and second.retries == 0


def test_queue_timeout_is_reported_without_retry():
    async def scenario():
        manager = RequestManager(max_concurrency=1, max_queue_size=2, queue_timeout_seconds=0.02)

        async def slow():
            await asyncio.sleep(0.1)
            return AttemptResult("ok", value="done")

        first = asyncio.create_task(manager.execute(slow))
        await asyncio.sleep(0.005)
        second = await manager.execute(slow)
        return await first, second

    first, second = run(scenario())
    assert first.status == "ok"
    assert second.status == "timeout" and second.error_code == "queue_timeout"
    assert second.retries == 0


def test_operation_exception_is_classified_and_not_retried():
    async def operation():
        raise RuntimeError("boom")

    result = run(RequestManager().execute(operation))
    assert result.status == "error" and result.error_code == "RuntimeError"
    assert result.attempts == 1 and result.retries == 0


def test_retry_policy_validation():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(jitter_fraction=2)
