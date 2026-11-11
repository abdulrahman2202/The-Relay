"""Make a modest number of real Groq calls to calibrate the Phase 4 stand-in.

The script deliberately does not attempt to exhaust quota.  It records observed
latency, token usage, streaming TTFT and one invalid-model error response.  It
never prints or writes the API key.
"""

from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relay.config import RelayConfig, load_api_key
from relay.errors import RelayError
from relay.llm import GroqService, RequestRecord
from relay.loadtest import percentile

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "reports" / "phase4" / "calibration" / "real-groq-calibration.json"
PHASE3 = ROOT / "reports" / "phase3" / "implementation-2026-11-11" / "real-groq-verification.json"


def safe_record(entry: RequestRecord) -> dict[str, Any]:
    data = asdict(entry)
    return {
        key: data.get(key)
        for key in (
            "stage",
            "model",
            "streaming",
            "started_utc",
            "status",
            "provider_model",
            "request_id",
            "finish_reason",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "duration_seconds",
            "first_token_seconds",
            "timeout_seconds",
            "error_code",
        )
    }


def entry_from_record(kind: str, record: RequestRecord, content: str | None) -> dict[str, Any]:
    data = safe_record(record)
    if record.status == "completed":
        status = "ok"
    elif record.error_code in {"rate_limit", "request_limit"}:
        status = "rate_limited"
    elif record.error_code == "timeout":
        status = "timeout"
    else:
        status = "error"
    return {
        "kind": kind,
        "status": status,
        "content": content,
        "start_time": data["started_utc"],
        "request": data,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate Phase 4 from modest real Groq calls")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-error-probe", action="store_true")
    args = parser.parse_args(argv)

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        api_key = load_api_key(ROOT / ".env")
    except RelayError as error:
        payload = {
            "available": False,
            "generated_utc": datetime.now(UTC).isoformat(),
            "reason": str(error),
            "note": "No real request was made. No credential is stored in this file.",
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Real calibration skipped: {error}")
        return 1

    config = RelayConfig(
        max_output_tokens=64,
        planning_tokens=64,
        request_timeout=30.0,
        turn_timeout=90.0,
    )
    service = GroqService(config, api_key=api_key)
    requests: list[dict[str, Any]] = []
    lock = threading.Lock()

    def add(kind: str, content: str | None = None, record: RequestRecord | None = None) -> None:
        if record is None:
            record = service.records[-1]
        entry = entry_from_record(kind, record, content)
        with lock:
            requests.append(entry)

    prompts = [
        ("non_streaming", "Reply with exactly: CALIBRATION OK"),
        ("non_streaming", "Reply with exactly: LATENCY ONE"),
        ("non_streaming", "Reply with exactly: TOKENS 42"),
    ]
    streams = [
        ("streaming", "Count from 1 to 5 separated by spaces."),
        ("streaming", "Reply with the three words: alpha beta gamma."),
        ("streaming", "Reply with exactly: STREAM OK"),
    ]
    try:
        for kind, prompt in prompts:
            try:
                completion = service.complete(
                    [{"role": "user", "content": prompt}], stage="calibration"
                )
                add(kind, completion.message.get("content"))
            except RelayError:
                add(kind)
        for kind, prompt in streams:
            parts: list[str] = []
            try:
                service.stream([{"role": "user", "content": prompt}], parts.append)
                add(kind, "".join(parts))
            except RelayError:
                add(kind)

        def concurrent_call(prompt: str) -> dict[str, Any]:
            local = GroqService(config, api_key=api_key)
            try:
                completion = local.complete(
                    [{"role": "user", "content": prompt}], stage="calibration"
                )
                return entry_from_record(
                    "concurrent", completion.request, completion.message.get("content")
                )
            except RelayError:
                return entry_from_record("concurrent", local.records[-1], None)
            finally:
                local.close()

        with ThreadPoolExecutor(max_workers=3) as pool:
            concurrent = list(
                pool.map(
                    concurrent_call,
                    [
                        "Reply with exactly: CONCURRENT A",
                        "Reply with exactly: CONCURRENT B",
                        "Reply with exactly: CONCURRENT C",
                    ],
                )
            )
        requests.extend(concurrent)

        if not args.skip_error_probe:
            error_config = RelayConfig(
                model="openai/gpt-oss-20b-does-not-exist",
                max_output_tokens=16,
                planning_tokens=16,
                request_timeout=20.0,
                turn_timeout=30.0,
            )
            probe = GroqService(error_config, api_key=api_key)
            try:
                probe.complete(
                    [{"role": "user", "content": "This model intentionally does not exist."}],
                    stage="calibration_error_probe",
                )
                add("error_probe", None, probe.records[-1])
            except RelayError:
                add("error_probe", None, probe.records[-1])
            finally:
                probe.close()
    finally:
        service.close()

    ok = [item for item in requests if item["status"] == "ok"]
    streaming = [
        item
        for item in ok
        if item["kind"] == "streaming" and item["request"]["first_token_seconds"] is not None
    ]
    ttft = [item["request"]["first_token_seconds"] * 1000.0 for item in streaming]
    totals = [item["request"]["duration_seconds"] * 1000.0 for item in ok]
    phase3_reference = None
    if PHASE3.is_file():
        phase3_reference = json.loads(PHASE3.read_text(encoding="utf-8")).get("checks")

    key_present = api_key in json.dumps(requests)
    if key_present:
        raise RuntimeError("Refusing to write calibration output containing the API key")

    payload = {
        "available": True,
        "generated_utc": datetime.now(UTC).isoformat(),
        "model": config.model,
        "quota_policy": {
            "requested_real_calls": len(requests),
            "intentional_rate_limit_exhaustion": False,
            "note": "No free-tier quota was deliberately exhausted. "
            "Rate-limit responses observed here: "
            f"{sum(1 for item in requests if item['status'] == 'rate_limited')}.",
        },
        "observations": {
            "successful": len(ok),
            "rate_limited": sum(1 for item in requests if item["status"] == "rate_limited"),
            "timeouts": sum(1 for item in requests if item["status"] == "timeout"),
            "errors": sum(1 for item in requests if item["status"] == "error"),
            "streaming_ttft_ms": {
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
            "tokens_in": sum(item["request"]["input_tokens"] or 0 for item in requests),
            "tokens_out": sum(item["request"]["output_tokens"] or 0 for item in requests),
        },
        "requests": requests,
        "phase3_reference": phase3_reference,
        "limitations": [
            "These are observations from a shared free-tier service, not a controlled benchmark.",
            "No rate-limit response was intentionally induced, so the 429 latency distribution "
            "is not measured.",
            "Concurrent calls are a tiny sample and are not a load test.",
        ],
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(
        f"Wrote {output} with {len(requests)} real requests "
        f"({len(ok)} successful, {len(streaming)} streaming TTFT samples)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
