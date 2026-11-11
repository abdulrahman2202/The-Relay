"""Run the reproducible Phase 4 stand-in load and retry experiments.

No real Groq calls are made here.  Real calibration is produced separately by
scripts/calibrate_phase4.py and merged into results/results.csv with
source=real.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relay.loadtest import RequestRow, run_load_scenario, write_jsonl, write_results_csv
from relay.mock.config import MockConfig
from relay.reliability import RetryPolicy

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "reports" / "phase4" / "calibration" / "real-groq-calibration.json"
RAW_DIR = ROOT / "results" / "phase4" / "raw"
SUMMARY_PATH = ROOT / "reports" / "phase4" / "load-test-summaries.json"
RESULTS_CSV = ROOT / "results" / "results.csv"

BASE_CONFIG = dict(
    seed=0,
    per_minute_limit=600,
    daily_request_budget=10_000,
    daily_token_budget=10_000_000,
    processing_delay_ms=650,
    max_concurrency=64,
    max_queue_size=256,
    queue_timeout_ms=5000,
    load_latency_ms_per_active=15,
    streaming_chunks=4,
    streaming_chunk_delay_ms=20,
    input_token_overhead=56,
)

RETRY_TWO = RetryPolicy(
    max_attempts=2,
    base_delay_seconds=0.05,
    max_delay_seconds=0.25,
    jitter_fraction=0.1,
)


def scenario_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "A-steady",
            "config": MockConfig(**BASE_CONFIG),
            "requests": 40,
            "rate_per_second": 8,
            "retry_policy": RETRY_TWO,
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 64,
            "manager_queue_timeout_seconds": 5.0,
        },
        {
            "name": "B-burst",
            "config": MockConfig(**BASE_CONFIG),
            "requests": 30,
            "rate_per_second": None,
            "retry_policy": RETRY_TWO,
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 64,
            "manager_queue_timeout_seconds": 5.0,
        },
        {
            "name": "C-overload",
            "config": MockConfig(
                **{
                    **BASE_CONFIG,
                    "scenario": "overloaded",
                    "processing_delay_ms": 150,
                    "max_concurrency": 2,
                    "max_queue_size": 4,
                    "queue_timeout_ms": 300,
                    "load_latency_ms_per_active": 120,
                }
            ),
            "requests": 80,
            "rate_per_second": 20,
            "retry_policy": RetryPolicy(max_attempts=1),
            "manager_max_concurrency": 20,
            "manager_max_queue_size": 128,
            "manager_queue_timeout_seconds": 2.0,
            "client_timeout": 5.0,
        },
        {
            "name": "D-per-minute-baseline",
            "config": MockConfig(**{**BASE_CONFIG, "per_minute_limit": 30}),
            "requests": 40,
            "rate_per_second": 8,
            "retry_policy": RetryPolicy(max_attempts=1),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 64,
            "manager_queue_timeout_seconds": 5.0,
        },
        {
            "name": "D-per-minute-halved",
            "config": MockConfig(**{**BASE_CONFIG, "per_minute_limit": 15}),
            "requests": 40,
            "rate_per_second": 8,
            "retry_policy": RetryPolicy(max_attempts=1),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 64,
            "manager_queue_timeout_seconds": 5.0,
        },
        {
            "name": "E-daily-budget",
            "config": MockConfig(
                **{
                    **BASE_CONFIG,
                    "daily_request_budget": 10,
                    "processing_delay_ms": 100,
                }
            ),
            "requests": 25,
            "rate_per_second": 10,
            "retry_policy": RetryPolicy(max_attempts=2, base_delay_seconds=0.01),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 64,
            "manager_queue_timeout_seconds": 5.0,
        },
    ]


def retry_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "retry-recovers",
            "config": MockConfig(
                processing_delay_ms=20,
                failure_on_requests=(1,),
                retry_after_seconds=0.001,
                max_concurrency=8,
            ),
            "requests": 1,
            "rate_per_second": None,
            "retry_policy": RetryPolicy(
                max_attempts=2,
                base_delay_seconds=0.01,
                max_delay_seconds=0.02,
                jitter_fraction=0,
            ),
            "manager_max_concurrency": 2,
            "manager_max_queue_size": 4,
            "manager_queue_timeout_seconds": 1.0,
        },
        {
            "name": "retry-worsens-no-retry",
            "config": MockConfig(
                processing_delay_ms=10,
                per_minute_limit=3,
                max_concurrency=8,
            ),
            "requests": 6,
            "rate_per_second": None,
            "retry_policy": RetryPolicy(max_attempts=1),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 16,
            "manager_queue_timeout_seconds": 2.0,
        },
        {
            "name": "retry-worsens-with-retry",
            "config": MockConfig(
                processing_delay_ms=10,
                per_minute_limit=3,
                max_concurrency=8,
            ),
            "requests": 6,
            "rate_per_second": None,
            "retry_policy": RetryPolicy(
                max_attempts=3,
                base_delay_seconds=0.01,
                max_delay_seconds=0.02,
                jitter_fraction=0,
                respect_retry_after=False,
            ),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 16,
            "manager_queue_timeout_seconds": 2.0,
        },
        {
            "name": "daily-budget-no-retry",
            "config": MockConfig(
                processing_delay_ms=10,
                daily_request_budget=3,
                max_concurrency=8,
            ),
            "requests": 5,
            "rate_per_second": None,
            "retry_policy": RetryPolicy(max_attempts=3, base_delay_seconds=0.01),
            "manager_max_concurrency": 8,
            "manager_max_queue_size": 16,
            "manager_queue_timeout_seconds": 2.0,
        },
    ]


def real_rows() -> list[RequestRow]:
    if not CALIBRATION.is_file():
        return []
    data = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    if not data.get("available"):
        return []
    rows: list[RequestRow] = []
    for index, item in enumerate(data.get("requests", []), 1):
        request = item.get("request") or {}
        request_id = request.get("request_id") or f"real-calibration-{index:03d}"
        first = request.get("first_token_seconds")
        total = request.get("duration_seconds")
        rows.append(
            RequestRow(
                request_id=str(request_id),
                scenario=f"real-{item.get('kind', 'calibration')}",
                source="real",
                start_time=str(item.get("start_time") or ""),
                first_token_ms=None if first is None else round(first * 1000.0, 3),
                total_ms=None if total is None else round(total * 1000.0, 3),
                status=item.get("status", "error"),
                retries=0,
                tokens_in=request.get("input_tokens"),
                tokens_out=request.get("output_tokens"),
            )
        )
    return rows


async def run_all() -> tuple[list[RequestRow], list[dict[str, Any]]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[RequestRow] = []
    summaries: list[dict[str, Any]] = []
    for spec in scenario_specs() + retry_specs():
        result = await run_load_scenario(**spec)
        write_jsonl(result.raw, RAW_DIR / f"{spec['name']}.jsonl")
        summaries.append(result.summary)
        all_rows.extend(result.rows)
        print(
            f"{spec['name']}: requests={result.summary['requests']} ok={result.summary['ok']} "
            f"rate_limited={result.summary['rate_limited']} "
            f"timeouts={result.summary['timeouts']} errors={result.summary['errors']} "
            f"retries={result.summary['retries']}"
        )
    return all_rows, summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 4 stand-in experiments")
    parser.add_argument(
        "--skip-real", action="store_true", help="Do not merge real calibration rows"
    )
    args = parser.parse_args(argv)
    standin_rows, summaries = asyncio.run(run_all())
    rows = [] if args.skip_real else real_rows()
    rows.extend(standin_rows)
    rows.sort(key=lambda row: (row.scenario, row.request_id))
    write_results_csv(rows, RESULTS_CSV)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(
            {
                "generated_utc": datetime.now(UTC).isoformat(),
                "simulated_notice": "Every stand-in measurement is simulated by "
                "src/relay/mock. Real calibration rows are separate.",
                "scenarios": summaries,
                "results_csv": str(RESULTS_CSV.relative_to(ROOT)),
                "raw_dir": str(RAW_DIR.relative_to(ROOT)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {RESULTS_CSV} with {len(rows)} rows and {SUMMARY_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
