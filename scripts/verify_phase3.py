"""Run a small, real Groq verification for Phase 3 and save safe evidence.

This script is intentionally outside the automated test suite: it contacts the
Groq API and the local RAG index. It never prints or stores the API key.
"""

import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pymupdf

from relay.config import RelayConfig, load_api_key
from relay.errors import RelayError
from relay.llm import GroqService, RequestRecord
from relay.orchestrator import ResearchAssistant
from relay.prompts import PROMPT_VERSION, SYSTEM
from relay.tools import ResearchTool, parse_tool_calls, tool_schema
from retrieval.catalog import PAPERS

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "reports" / "phase3" / "implementation-2026-11-11" / "real-groq-verification.json"
ANSWERABLE = "What are Moshi's theoretical and practical latency?"
UNSUPPORTED = "What p95 latency does Moshi measure on iPhone 15 Pro running iOS?"
MODEL_REFUSAL = "How much did it cost in dollars to train Moshi?"


def record(entry: RequestRecord) -> dict:
    return {
        key: value
        for key, value in asdict(entry).items()
        if key
        in {
            "stage",
            "model",
            "streaming",
            "status",
            "provider_model",
            "request_id",
            "completion_id",
            "finish_reason",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "duration_seconds",
            "first_token_seconds",
            "prompt_budget_upper_bound",
            "max_output_tokens",
            "timeout_seconds",
            "tool_names",
            "error_code",
        }
    }


def safe_call(name: str, function) -> dict:
    try:
        return {"name": name, "ok": True, **function()}
    except RelayError as exc:
        return {"name": name, "ok": False, "error": exc.to_dict()}
    except Exception as exc:  # Do not leak provider bodies or local paths.
        return {
            "name": name,
            "ok": False,
            "error": {"code": "unexpected", "type": type(exc).__name__},
        }


def normalize_pdf_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("-\n", "")
    return " ".join(text.replace("\n", " ").split()).replace("-", "")


def check_quote_in_pdf(quote: str, arxiv_id: str, version: int, pages: tuple[int, ...]) -> dict:
    paper = next((item for item in PAPERS if item.arxiv_id == arxiv_id), None)
    if paper is None or paper.version != version:
        return {"ok": False, "reason": "unknown paper version"}
    path = ROOT / "papers" / paper.filename
    with pymupdf.open(path) as document:
        needle = normalize_pdf_text(quote)
        for page in pages:
            if not 1 <= page <= document.page_count:
                continue
            if needle in normalize_pdf_text(document[page - 1].get_text("text")):
                return {"ok": True, "page": page, "file": paper.filename}
    return {"ok": False, "reason": "quote not found on cited page(s)"}


def citation_pdf_checks(result) -> list[dict]:
    checks = []
    for claim in result.claims:
        for citation in claim["citations"]:
            checks.append(
                {
                    "source_id": citation["source_id"],
                    "arxiv_id": citation["arxiv_id"],
                    "version": citation["version"],
                    "pages": citation["pages"],
                    "quote": citation["quote"],
                    **check_quote_in_pdf(
                        citation["quote"],
                        citation["arxiv_id"],
                        citation["version"],
                        tuple(citation["pages"]),
                    ),
                }
            )
    return checks


def main() -> int:
    config = RelayConfig.from_env(ROOT / ".env")
    service = GroqService(config, api_key=load_api_key(ROOT / ".env"))
    tool = ResearchTool(config)
    assistant = ResearchAssistant(config, service, tool)
    report = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "model": config.model,
        "prompt_version": PROMPT_VERSION,
        "checks": [],
    }
    started = time.perf_counter()

    report["checks"].append(
        safe_call(
            "normal_completion",
            lambda: (
                lambda reply: {
                    "content": reply.message.get("content"),
                    "request": record(reply.request),
                }
            )(
                service.complete(
                    [
                        {"role": "system", "content": "Answer briefly."},
                        {"role": "user", "content": "Reply with exactly: RELAY OK"},
                    ]
                )
            ),
        )
    )

    def stream_check():
        parts = []
        request = service.stream(
            [{"role": "user", "content": "Count from 1 to 5, space separated, no other text."}],
            parts.append,
        )
        return {"text": "".join(parts), "request": record(request)}

    report["checks"].append(safe_call("streaming_completion", stream_check))

    def tool_check():
        question = ANSWERABLE
        planned = service.complete(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
            stage="planning",
            tools=[tool_schema(config)],
            tool_choice="required",
        )
        calls = parse_tool_calls(planned.message, config)
        executions = [tool.execute(call) for call in calls]
        return {
            "question": question,
            "request": record(planned.request),
            "calls": [asdict(call) for call in calls],
            "executions": [
                {
                    "status": "failed" if item.error else ("evidence" if item.hits else "empty"),
                    "seconds": item.seconds,
                    "hits": [
                        {
                            "chunk_id": hit.chunk_id,
                            "paper_title": hit.paper_title,
                            "arxiv_id": hit.arxiv_id,
                            "version": hit.version,
                            "pages": list(hit.pages),
                        }
                        for hit in item.hits
                    ],
                    "error": item.error.to_dict() if item.error else None,
                }
                for item in executions
            ],
        }

    report["checks"].append(safe_call("real_tool_call_and_retrieval", tool_check))

    def ask_check(question: str):
        result = assistant.ask(question)
        return {
            "question": question,
            "status": result.status,
            "answer": result.answer,
            "stages": result.stages,
            "tools": result.tools,
            "evidence_assessment": result.evidence_assessment,
            "claims": result.claims,
            "sources": result.sources,
            "metrics": asdict(result.metrics),
            "requests": [record(item) for item in result.requests],
            "error": result.error,
            "citation_pdf_checks": citation_pdf_checks(result),
        }

    report["checks"].append(
        safe_call("answerable_research_question", lambda: ask_check(ANSWERABLE))
    )
    report["checks"].append(
        safe_call("unsupported_constraint_question", lambda: ask_check(UNSUPPORTED))
    )
    report["checks"].append(safe_call("model_refusal_question", lambda: ask_check(MODEL_REFUSAL)))
    report["elapsed_seconds"] = time.perf_counter() - started
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    service.close()
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
