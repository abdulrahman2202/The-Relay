"""Compare production retrieval strategies on the Phase 3 evaluation questions.

This is an offline retrieval evaluation. It uses the production search/context/evidence
functions with the default 600-token preset and leaves the application settings unchanged.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from retrieval.config import PRESETS
from retrieval.context import select_context
from retrieval.evidence import assess_evidence, infer_requirements
from retrieval.models import SearchHit
from retrieval.pipeline import RetrievalPipeline

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "reports/phase3/evaluation/questions.json"
GOLD_PATH = ROOT / "reports/rag/improvements-2026-11-11/evaluation-final/evidence.json"
OUTPUT_DIR = ROOT / "reports/final-evaluation"
CSV_PATH = OUTPUT_DIR / "retrieval-comparison.csv"
SUMMARY_PATH = OUTPUT_DIR / "retrieval-comparison-summary.json"
RAW_PATH = OUTPUT_DIR / "raw/retrieval-rankings.json"

STRATEGIES = ("vector", "bm25", "hybrid")
TOP_K = PRESETS[600].top_k
RANKING_K = 50
MAX_CONTEXT_TOKENS = 3000

GOLD_MAPPING = {
    "A1": "M1",
    "A2": "A4",
    "A3": "A3",
    "A4": "A2",
    "A5": "M2",
    "A6": "M3",
    "A7": "M4",
    "A8": "H1",
    "A9": "H2",
    "A10": "H3",
    "A11": "H4",
    "A12": "A1",
}

TARGET_PAPER = {
    "U1": "2410.00037",
    "U2": "2410.00037",
    "U3": "1706.03762",
    "U4": "2507.07955",
    "U5": "2410.00037",
    "U6": "1706.03762",
    "U7": "2410.00037",
    "U8": "2507.07955",
}

FIELDS = [
    "question_id",
    "category",
    "question",
    "strategy",
    "top_k",
    "ranking_k",
    "max_context_tokens",
    "retrieval_total_ms",
    "ranking_latency_ms",
    "context_selection_ms",
    "retrieved_count",
    "retrieved_tokens_top_k",
    "context_count",
    "context_tokens",
    "first_relevant_rank",
    "first_all_units_rank",
    "target_paper_first_rank",
    "relevant_hits_top_k",
    "coverage_units",
    "coverage_total",
    "coverage_complete",
    "context_coverage_complete",
    "evidence_refused",
    "refusal_expected",
    "false_refusal",
    "notes",
]


def covered(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    cursor = start
    for left, right in sorted(intervals):
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return cursor >= end


def coverage(gold: dict[str, Any], hits: list[SearchHit] | tuple[SearchHit, ...]) -> list[bool]:
    intervals = [
        (hit.char_start, hit.char_start + len(hit.text))
        for hit in hits
        if hit.arxiv_id == gold["paper"] and hit.char_start is not None
    ]
    return [
        any(
            all(covered(span["start_char"], span["end_char"], intervals) for span in alternative)
            for alternative in unit["alternatives"]
        )
        for unit in gold["units"]
    ]


def first_rank(gold: dict[str, Any], hits: list[SearchHit], complete: bool) -> int | None:
    for index in range(1, len(hits) + 1):
        values = coverage(gold, hits[:index])
        if all(values) if complete else any(values):
            return index
    return None


def token_count(tokenizer: Any, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False))


def evaluate() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    gold_source = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    gold = {item["id"]: item for item in gold_source["answerable"]}
    questions = [{**item, "category": "answerable"} for item in source["answerable"]] + [
        {**item, "category": "unanswerable"} for item in source["unanswerable"]
    ]
    pipeline = RetrievalPipeline(
        papers_dir=ROOT / "papers",
        db_dir=ROOT / "data/chroma-v2",
        config=PRESETS[600],
    )
    tokenizer = pipeline.embedder.tokenizer
    for strategy in STRATEGIES:
        pipeline.search("retrieval warmup", strategy=strategy, top_k=TOP_K)
    rows: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    for item in questions:
        gold_item = gold[GOLD_MAPPING[item["id"]]] if item["category"] == "answerable" else None
        target_paper = item.get("relevant_paper") or TARGET_PAPER[item["id"]]
        target_paper = re.sub(r"v\d+$", "", target_paper.removeprefix("arXiv:"))
        raw[item["id"]] = {}
        for strategy in STRATEGIES:
            started = time.perf_counter()
            ranking = pipeline.search(item["question"], strategy=strategy, top_k=RANKING_K)
            ranking_seconds = time.perf_counter() - started
            context_started = time.perf_counter()
            context = select_context(
                ranking[:TOP_K],
                tokenizer,
                max_tokens=MAX_CONTEXT_TOKENS,
                query=item["question"],
            )
            context_seconds = time.perf_counter() - context_started
            assessment = assess_evidence(context.hits, infer_requirements(item["question"]))
            production_hits = ranking[:TOP_K]
            if gold_item is not None:
                values = coverage(gold_item, production_hits)
                context_values = coverage(gold_item, context.hits)
                coverage_units = sum(values)
                coverage_total = len(values)
                coverage_complete = int(all(values))
                context_complete = int(all(context_values))
                relevant_rank = first_rank(gold_item, ranking, complete=False)
                all_units_rank = first_rank(gold_item, ranking, complete=True)
                relevant_hits = sum(bool(coverage(gold_item, [hit])) for hit in production_hits)
            else:
                coverage_units = ""
                coverage_total = ""
                coverage_complete = ""
                context_complete = ""
                relevant_rank = ""
                all_units_rank = ""
                relevant_hits = ""
            target_rank = next(
                (index for index, hit in enumerate(ranking, 1) if hit.arxiv_id == target_paper),
                None,
            )
            row = {
                "question_id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "strategy": strategy,
                "top_k": TOP_K,
                "ranking_k": RANKING_K,
                "max_context_tokens": MAX_CONTEXT_TOKENS,
                "retrieval_total_ms": round((ranking_seconds + context_seconds) * 1000.0, 3),
                "ranking_latency_ms": round(ranking_seconds * 1000.0, 3),
                "context_selection_ms": round(context_seconds * 1000.0, 3),
                "retrieved_count": len(ranking),
                "retrieved_tokens_top_k": sum(
                    token_count(tokenizer, hit.text) for hit in production_hits
                ),
                "context_count": len(context.hits),
                "context_tokens": context.token_count,
                "first_relevant_rank": relevant_rank if relevant_rank is not None else "",
                "first_all_units_rank": all_units_rank if all_units_rank is not None else "",
                "target_paper_first_rank": target_rank if target_rank is not None else "",
                "relevant_hits_top_k": relevant_hits,
                "coverage_units": coverage_units,
                "coverage_total": coverage_total,
                "coverage_complete": coverage_complete,
                "context_coverage_complete": context_complete,
                "evidence_refused": int(assessment.refused),
                "refusal_expected": int(item["category"] == "unanswerable"),
                "false_refusal": int(item["category"] == "answerable" and assessment.refused),
                "notes": (
                    "No gold answer span; target-paper rank and refusal behavior only."
                    if item["category"] == "unanswerable"
                    else ""
                ),
            }
            rows.append(row)
            raw[item["id"]][strategy] = {
                "hits": [
                    {
                        "rank": index,
                        "chunk_id": hit.chunk_id,
                        "arxiv_id": hit.arxiv_id,
                        "pages": list(hit.pages),
                        "score": hit.score,
                        "score_type": hit.to_dict()["score_type"],
                        "covered_units": coverage(gold_item, [hit]) if gold_item else None,
                    }
                    for index, hit in enumerate(ranking, 1)
                ],
                "context_ids": [hit.chunk_id for hit in context.hits],
                "context_tokens": context.token_count,
                "assessment": asdict(assessment),
            }
        print(f"{item['id']} retrieved", flush=True)
    summary = []
    for strategy in STRATEGIES:
        selected = [row for row in rows if row["strategy"] == strategy]
        answerable = [row for row in selected if row["category"] == "answerable"]
        unanswerable = [row for row in selected if row["category"] == "unanswerable"]
        ranks = [row["first_relevant_rank"] for row in answerable if row["first_relevant_rank"]]
        summary.append(
            {
                "strategy": strategy,
                "answerable_questions": len(answerable),
                "complete_coverage": sum(bool(row["coverage_complete"]) for row in answerable),
                "complete_context_coverage": sum(
                    bool(row["context_coverage_complete"]) for row in answerable
                ),
                "false_refusals": sum(row["false_refusal"] for row in answerable),
                "mean_reciprocal_rank": round(
                    sum(1.0 / rank for rank in ranks) / len(answerable), 4
                )
                if answerable
                else None,
                "mean_first_relevant_rank": round(sum(ranks) / len(ranks), 3) if ranks else None,
                "unsupported_questions": len(unanswerable),
                "unsupported_refusals": sum(row["evidence_refused"] for row in unanswerable),
                "mean_context_tokens": round(
                    sum(row["context_tokens"] for row in answerable) / len(answerable), 3
                )
                if answerable
                else None,
                "mean_retrieval_total_ms": round(
                    sum(row["retrieval_total_ms"] for row in selected) / len(selected), 3
                ),
                "mean_ranking_latency_ms": round(
                    sum(row["ranking_latency_ms"] for row in selected) / len(selected), 3
                ),
                "mean_context_tokens_all_questions": round(
                    sum(row["context_tokens"] for row in selected) / len(selected), 3
                ),
            }
        )
    protocol = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "measurement_type": "offline_local_retrieval",
        "simulated": False,
        "questions_source": str(QUESTIONS_PATH.relative_to(ROOT)),
        "gold_annotation_source": str(GOLD_PATH.relative_to(ROOT)),
        "gold_mapping": GOLD_MAPPING,
        "strategies": list(STRATEGIES),
        "preset": 600,
        "top_k": TOP_K,
        "ranking_k": RANKING_K,
        "max_context_tokens": MAX_CONTEXT_TOKENS,
        "chunking": PRESETS[600].indexing_settings,
        "bm25_k1": PRESETS[600].bm25_k1,
        "bm25_b": PRESETS[600].bm25_b,
        "rrf_constant": PRESETS[600].rrf_constant,
        "warmup": "One search per strategy before timing.",
        "notes": [
            "Production defaults were not changed.",
            "Unanswerable questions have no gold answer span; coverage and rank are blank.",
            "Coverage measures annotated evidence spans, not generated-answer correctness.",
        ],
    }
    return rows, summary, {"protocol": protocol, "questions": raw}


def write(rows: list[dict[str, Any]], summary: list[dict[str, Any]], raw: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY_PATH.write_text(
        json.dumps(
            {
                "generated_utc": raw["protocol"]["generated_utc"],
                "protocol": raw["protocol"],
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    RAW_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    rows, summary, raw = evaluate()
    write(rows, summary, raw)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {CSV_PATH.relative_to(ROOT)} with {len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
