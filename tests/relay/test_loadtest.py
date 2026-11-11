import asyncio
import csv
from pathlib import Path

import pytest

from relay.loadtest import (
    CSV_COLUMNS,
    RequestRow,
    read_results_csv,
    run_load_scenario,
    validate_rows,
    write_results_csv,
)
from relay.mock.config import MockConfig
from relay.reliability import RetryPolicy


def test_steady_load_generates_rows_and_summary():
    result = asyncio.run(
        run_load_scenario(
            name="steady-test",
            config=MockConfig(processing_delay_ms=5, per_minute_limit=100),
            requests=6,
            rate_per_second=40,
            retry_policy=RetryPolicy(max_attempts=1),
            manager_max_concurrency=2,
            manager_max_queue_size=16,
        )
    )
    assert result.summary["requests"] == 6
    assert result.summary["ok"] == 6
    assert result.summary["given_up"] == 0
    assert result.summary["ttft_ms"]["samples"] == 6
    assert result.summary["total_ms"]["p50"] is not None
    assert result.summary["tokens_in"] > 0 and result.summary["tokens_out"] > 0
    assert {row.status for row in result.rows} == {"ok"}


def test_rate_limited_load_preserves_allowed_status_and_retry_metadata():
    result = asyncio.run(
        run_load_scenario(
            name="rate-test",
            config=MockConfig(processing_delay_ms=1, per_minute_limit=1),
            requests=3,
            rate_per_second=None,
            retry_policy=RetryPolicy(max_attempts=1),
            manager_max_concurrency=4,
            manager_max_queue_size=16,
        )
    )
    assert result.summary["ok"] == 1
    assert result.summary["rate_limited"] == 2
    assert result.summary["given_up"] == 2
    assert {row.status for row in result.rows} <= {"ok", "rate_limited"}


def test_retry_recovery_is_reflected_in_load_row():
    result = asyncio.run(
        run_load_scenario(
            name="recovery-test",
            config=MockConfig(
                processing_delay_ms=1,
                failure_on_requests=(1,),
                retry_after_seconds=0.001,
            ),
            requests=1,
            retry_policy=RetryPolicy(
                max_attempts=2,
                base_delay_seconds=0.001,
                max_delay_seconds=0.002,
                jitter_fraction=0,
            ),
            manager_max_concurrency=2,
            manager_max_queue_size=4,
        )
    )
    assert result.summary["ok"] == 1 and result.summary["retries"] == 1
    assert result.rows[0].retries == 1


def test_csv_round_trip_uses_exact_required_schema(tmp_path: Path):
    rows = [
        RequestRow(
            request_id="stand-in-test-0001",
            scenario="steady",
            source="stand-in",
            start_time="2026-11-11T00:00:00+00:00",
            first_token_ms=12.5,
            total_ms=30.0,
            status="ok",
            retries=0,
            tokens_in=10,
            tokens_out=4,
        ),
        RequestRow(
            request_id="real-test-0001",
            scenario="real-baseline",
            source="real",
            start_time="2026-11-11T00:00:01+00:00",
            first_token_ms=None,
            total_ms=500.0,
            status="rate_limited",
            retries=0,
            tokens_in=None,
            tokens_out=None,
        ),
    ]
    path = tmp_path / "results.csv"
    write_results_csv(rows, path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    assert header == CSV_COLUMNS
    loaded = read_results_csv(path)
    assert len(loaded) == 2
    assert loaded[0]["answer_grade"] == "" and loaded[0]["retrieval_setting"] == ""


def test_csv_validation_rejects_invalid_values_and_schema():
    good = RequestRow(
        "x",
        "s",
        "stand-in",
        "2026-11-11T00:00:00+00:00",
        1.0,
        2.0,
        "ok",
        0,
        1,
        1,
    ).csv_dict()
    validate_rows([good])
    bad_status = dict(good, status="success")
    with pytest.raises(ValueError):
        validate_rows([bad_status])
    bad_source = dict(good, source="groq")
    with pytest.raises(ValueError):
        validate_rows([bad_source])
    bad_grade = dict(good, answer_grade="maybe")
    with pytest.raises(ValueError):
        validate_rows([bad_grade])
    extra = dict(good, unexpected="value")
    with pytest.raises(ValueError):
        validate_rows([extra])
    missing = {key: value for key, value in good.items() if key != "tokens_in"}
    with pytest.raises(ValueError):
        validate_rows([missing])
