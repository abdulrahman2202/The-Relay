"""Run the final Phase 5 end-to-end answer-quality evaluation against real Groq.

The script does not modify application code or Phase 1-4 evidence. It writes new
artifacts under reports/final-evaluation and leaves final grades pending manual review.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relay.cli import build_assistant
from relay.config import RelayConfig
from relay.prompts import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "reports/phase3/evaluation/questions.json"
OUTPUT_DIR = ROOT / "reports/final-evaluation"
RESULTS_PATH = OUTPUT_DIR / "answer-quality-results.json"
MANUAL_PATH = OUTPUT_DIR / "manual-grading.csv"
RAW_PATH = OUTPUT_DIR / "raw/answer-quality-raw.json"

GRADE_VALUES = {"correct", "wrong", "refused_correctly", "refused_wrongly"}

A4_CONFLICT = {
    "description": (
        "Attention Is All You Need reports English-to-French BLEU 41.8 in Table 2 "
        "and 41.0 in the prose on physical page 8. The conflict must not be silently "
        "hidden or resolved by inventing a third value."
    ),
    "table_2": {
        "page": 8,
        "english_to_german": 28.4,
        "english_to_french": 41.8,
        "verified_quote": "Transformer (big) | 28.4 | 41.8",
    },
    "prose": {
        "page": 8,
        "english_to_french": 41.0,
        "verified_quote": (
            "our big model achieves a BLEU score of 41.0, outperforming all of the previously "
            "published single models"
        ),
    },
    "provenance": "reports/rag/audit-2026-11-11/questions.json (A2) and direct PDF page 8 check",
    "review_requirement": "Identify the discrepancy explicitly in the final review.",
}


def normalized(text: str) -> str:
    return " ".join(text.split())


def numbers(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).replace("−", "-")
    values = re.findall(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)*", text)
    return {
        value.replace(",", "") if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+", value) else value
        for value in values
    }


def citation_label(citation: dict[str, Any]) -> str:
    pages = [int(page) for page in citation.get("pages") or []]
    page_text = ", ".join(str(page) for page in pages)
    prefix = "p." if len(pages) == 1 else "pp."
    return (
        f"{citation.get('paper_title')} "
        f"(arXiv:{citation.get('arxiv_id')}v{citation.get('version')}, {prefix} {page_text})"
    )


def validate_citations(result: Any) -> dict[str, Any]:
    sources = {source["source_id"]: source for source in result.sources}
    errors: list[str] = []
    citations: list[dict[str, Any]] = []
    for claim in result.claims:
        claim_text = claim.get("text", "")
        claim_numbers = numbers(claim_text)
        quote_numbers: set[str] = set()
        for citation in claim.get("citations", []):
            source = sources.get(citation.get("source_id"))
            quote = citation.get("quote", "")
            if source is None:
                errors.append(f"unknown source {citation.get('source_id')}")
            else:
                if normalized(quote) not in normalized(source["text"]):
                    errors.append(f"quote absent from {citation.get('source_id')}")
                if source.get("arxiv_id") != citation.get("arxiv_id"):
                    errors.append(f"arXiv mismatch for {citation.get('source_id')}")
                if source.get("version") != citation.get("version"):
                    errors.append(f"version mismatch for {citation.get('source_id')}")
                if not set(citation.get("pages") or []).issubset(set(source.get("pages") or [])):
                    errors.append(f"page mismatch for {citation.get('source_id')}")
            quote_numbers.update(numbers(quote))
            citations.append(
                {
                    "source_id": citation.get("source_id"),
                    "paper_title": citation.get("paper_title"),
                    "arxiv_id": citation.get("arxiv_id"),
                    "version": citation.get("version"),
                    "pages": citation.get("pages"),
                    "source_url": citation.get("source_url"),
                    "quote": quote,
                    "label": citation_label(citation),
                }
            )
        if not claim_numbers <= quote_numbers:
            errors.append("claim numbers absent from supporting quotations")
    if result.status == "answered":
        validity = "valid" if citations and not errors else "invalid"
    elif result.status == "refused":
        validity = "not_applicable_refused"
    else:
        validity = "not_applicable_failed"
    return {
        "status": validity,
        "claim_count": len(result.claims),
        "citation_count": len(citations),
        "quotes_present": bool(citations) and not any("quote absent" in e for e in errors),
        "numbers_supported": bool(citations) and not any("numbers absent" in e for e in errors),
        "errors": errors,
        "citations": citations,
    }


def supporting_summary(citations: list[dict[str, Any]]) -> dict[str, Any]:
    papers: list[str] = []
    pages: list[str] = []
    labels: list[str] = []
    seen_labels = set()
    for citation in citations:
        label = citation["label"]
        if label in seen_labels:
            continue
        seen_labels.add(label)
        papers.append(citation["paper_title"])
        page_text = ", ".join(str(page) for page in citation.get("pages") or [])
        pages.append(f"arXiv:{citation.get('arxiv_id')} p. {page_text}")
        labels.append(label)
    return {
        "papers": list(dict.fromkeys(papers)),
        "pages": list(dict.fromkeys(pages)),
        "labels": labels,
    }


def provisional_grade(category: str, status: str, citation_validity: str) -> str | None:
    if status == "failed":
        return None
    if category == "answerable":
        if status == "refused":
            return "refused_wrongly"
        if status == "answered" and citation_validity == "invalid":
            return "wrong"
        return None
    if status == "refused":
        return "refused_correctly"
    if status == "answered":
        return "wrong"
    return None


def build_entry(
    meta: dict[str, Any], category: str, result: Any, attempts: list[dict[str, Any]]
) -> dict[str, Any]:
    citation_check = validate_citations(result)
    support = supporting_summary(citation_check["citations"])
    metrics = result.metrics
    expected = "answer" if category == "answerable" else "refuse"
    behavior_matches = (expected == "answer" and result.status == "answered") or (
        expected == "refuse" and result.status == "refused"
    )
    entry: dict[str, Any] = {
        "id": meta["id"],
        "category": category,
        "question": meta["question"],
        "expected_behavior": expected,
        "relevant_paper": meta.get("relevant_paper"),
        "note": meta.get("note") or meta.get("reason"),
        "status": result.status,
        "answer": result.answer,
        "claims": result.claims,
        "supporting": support,
        "citation_validation": {
            key: value for key, value in citation_check.items() if key != "citations"
        },
        "citations": citation_check["citations"],
        "evidence_assessment": result.evidence_assessment,
        "metrics": {
            "total_ms": round(metrics.total_seconds * 1000.0, 3),
            "ttft_ms": round(metrics.first_answer_token_seconds * 1000.0, 3)
            if metrics.first_answer_token_seconds is not None
            else None,
            "generation_first_token_ms": round(metrics.generation_first_token_seconds * 1000.0, 3)
            if metrics.generation_first_token_seconds is not None
            else None,
            "retrieval_ms": round(metrics.retrieval_seconds * 1000.0, 3),
            "evidence_selection_ms": round(metrics.evidence_selection_seconds * 1000.0, 3),
            "citation_validation_ms": round(metrics.citation_validation_seconds * 1000.0, 3),
            "planning_ms": round(metrics.llm_planning_seconds * 1000.0, 3),
            "generation_ms": round(metrics.llm_generation_seconds * 1000.0, 3),
            "input_tokens": metrics.input_tokens,
            "output_tokens": metrics.output_tokens,
            "known_input_tokens": metrics.known_input_tokens,
            "known_output_tokens": metrics.known_output_tokens,
            "evidence_tokens": metrics.evidence_tokens,
            "tool_calls": metrics.tool_calls,
        },
        "tools": result.tools,
        "stages": result.stages,
        "requests": [request.__dict__ for request in result.requests],
        "error": result.error,
        "failure_diagnostics": result.failure_diagnostics,
        "attempts": attempts,
        "behavior_matches_expectation": behavior_matches,
        "grade_status": "pending_manual_review",
        "provisional_grade": provisional_grade(category, result.status, citation_check["status"]),
        "final_grade": "",
    }
    if meta["id"] == "A4":
        entry["known_source_conflict"] = {
            **A4_CONFLICT,
            "answer_mentions_28_4": "28.4" in result.answer,
            "answer_mentions_41_8": "41.8" in result.answer,
            "answer_mentions_41_0": "41.0" in result.answer,
            "exposes_both_values": "41.8" in result.answer and "41.0" in result.answer,
        }
    return entry


def ask_with_attempts(assistant: Any, question: str, max_attempts: int) -> tuple[Any, list]:
    attempts: list[dict[str, Any]] = []
    result = None
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        result = assistant.ask(question)
        delay = 0.0
        retryable = bool(result.error and result.error.get("retryable"))
        attempts.append(
            {
                "attempt": attempt,
                "status": result.status,
                "error_code": result.error.get("code") if result.error else None,
                "retryable": retryable,
                "failure_diagnostics": result.failure_diagnostics,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            }
        )
        if not retryable or attempt == max_attempts:
            break
        delay = 5.0 * attempt
        if result.error.get("retry_after_seconds") is not None:
            delay = min(30.0, max(delay, float(result.error["retry_after_seconds"])))
        time.sleep(delay)
    return result, attempts


def load_existing() -> tuple[dict[str, Any], dict[str, Any]]:
    if not RESULTS_PATH.exists():
        return {}, {}
    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    entries = {entry["id"]: entry for entry in payload.get("results", [])}
    raw = {}
    if RAW_PATH.exists():
        raw = json.loads(RAW_PATH.read_text(encoding="utf-8")).get("entries", {})
    return entries, raw


def read_manual_review() -> dict[str, dict[str, str]]:
    if not MANUAL_PATH.exists():
        return {}
    with MANUAL_PATH.open(encoding="utf-8", newline="") as handle:
        return {row["question_id"]: row for row in csv.DictReader(handle)}


def write_artifacts(
    questions: list[dict[str, Any]],
    entries: dict[str, Any],
    raw: dict[str, Any],
    config: RelayConfig,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = [entries[item["id"]] for item in questions if item["id"] in entries]
    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "measurement_type": "real_groq_end_to_end",
        "simulated": False,
        "model": config.model,
        "prompt_version": PROMPT_VERSION,
        "conditions": {
            "strategy": config.strategy,
            "preset": config.preset,
            "evidence_tokens": config.evidence_tokens,
            "max_tool_calls": config.max_tool_calls,
            "request_timeout_seconds": config.request_timeout,
            "turn_timeout_seconds": config.turn_timeout,
            "temperature": 0,
            "seed": 0,
        },
        "questions_source": str(QUESTIONS_PATH.relative_to(ROOT)),
        "counts": {
            "total": len(ordered),
            "answerable": sum(entry["category"] == "answerable" for entry in ordered),
            "unanswerable": sum(entry["category"] == "unanswerable" for entry in ordered),
            "answered": sum(entry["status"] == "answered" for entry in ordered),
            "refused": sum(entry["status"] == "refused" for entry in ordered),
            "failed": sum(entry["status"] == "failed" for entry in ordered),
        },
        "grade_status": "pending_manual_review",
        "grade_values": sorted(GRADE_VALUES),
        "known_source_conflicts": {"A4": A4_CONFLICT},
        "results": ordered,
    }
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    RAW_PATH.write_text(
        json.dumps(
            {
                "generated_utc": payload["generated_utc"],
                "measurement_type": payload["measurement_type"],
                "entries": raw,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    review = read_manual_review()
    columns = [
        "question_id",
        "category",
        "question",
        "expected_behavior",
        "actual_status",
        "answer",
        "supporting_paper",
        "supporting_pages",
        "citations",
        "citation_validity",
        "behavior_matches_expectation",
        "provisional_grade",
        "final_grade",
        "reviewer_notes",
        "total_ms",
        "ttft_ms",
        "input_tokens",
        "output_tokens",
        "conflict_note",
    ]
    with MANUAL_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for entry in ordered:
            old = review.get(entry["id"], {})
            conflict = entry.get("known_source_conflict", {})
            writer.writerow(
                {
                    "question_id": entry["id"],
                    "category": entry["category"],
                    "question": entry["question"],
                    "expected_behavior": entry["expected_behavior"],
                    "actual_status": entry["status"],
                    "answer": entry["answer"],
                    "supporting_paper": "; ".join(entry["supporting"]["papers"]),
                    "supporting_pages": "; ".join(entry["supporting"]["pages"]),
                    "citations": "; ".join(entry["supporting"]["labels"]),
                    "citation_validity": entry["citation_validation"]["status"],
                    "behavior_matches_expectation": entry["behavior_matches_expectation"],
                    "provisional_grade": entry["provisional_grade"] or "",
                    "final_grade": old.get("final_grade", ""),
                    "reviewer_notes": old.get("reviewer_notes", ""),
                    "total_ms": entry["metrics"]["total_ms"],
                    "ttft_ms": entry["metrics"]["ttft_ms"] or "",
                    "input_tokens": entry["metrics"]["input_tokens"] or "",
                    "output_tokens": entry["metrics"]["output_tokens"] or "",
                    "conflict_note": conflict.get("description", ""),
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Comma-separated question IDs to run")
    parser.add_argument("--overwrite", action="store_true", help="Discard existing results")
    parser.add_argument("--sleep", type=float, default=1.0, help="Delay between questions")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args(argv)
    if args.sleep < 0:
        parser.error("--sleep must be nonnegative")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")

    source = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    questions = [{**item, "category": "answerable"} for item in source["answerable"]] + [
        {**item, "category": "unanswerable"} for item in source["unanswerable"]
    ]
    selected = set(args.only.split(",")) if args.only else {item["id"] for item in questions}
    unknown = selected - {item["id"] for item in questions}
    if unknown:
        parser.error(f"unknown question IDs: {sorted(unknown)}")

    entries, raw = {} if args.overwrite else load_existing()
    config = RelayConfig.from_env(
        ROOT / ".env",
        papers_dir=ROOT / "papers",
        db_dir=ROOT / "data/chroma-v2",
    )
    assistant = build_assistant(config, ROOT / ".env")
    try:
        for index, meta in enumerate(questions, 1):
            if meta["id"] not in selected:
                continue
            print(f"[{index}/{len(questions)}] {meta['id']} {meta['question']}", flush=True)
            result, attempts = ask_with_attempts(assistant, meta["question"], args.max_attempts)
            entry = build_entry(meta, meta["category"], result, attempts)
            entries[meta["id"]] = entry
            raw[meta["id"]] = {
                "result": result.to_dict(),
                "attempts": attempts,
            }
            write_artifacts(questions, entries, raw, config)
            print(
                f"  status={result.status} citations={entry['citation_validation']['status']} "
                f"total_ms={entry['metrics']['total_ms']}",
                flush=True,
            )
            if index < len(questions):
                time.sleep(args.sleep)
    finally:
        try:
            assistant.llm.close()
        except Exception:
            pass
    write_artifacts(questions, entries, raw, config)
    print(f"Wrote {RESULTS_PATH.relative_to(ROOT)} and {MANUAL_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
