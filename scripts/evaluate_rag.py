"""Repeat the audit questions against production retrieval; no answer generation.

Run from the repository root. Baseline reports are read-only. Each output directory
is an experiment record and must be new for a full run.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import logging
import re
import socket
import unicodedata
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from retrieval.config import PRESETS
from retrieval.context import select_context
from retrieval.evidence import assess_evidence, infer_requirements
from retrieval.index import ChromaIndex
from retrieval.models import ExtractedPaper, SearchHit
from retrieval.pipeline import RetrievalPipeline

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "reports/rag/audit-2026-11-11"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical(text: str) -> tuple[str, list[int]]:
    """Map presentation changes to source positions; retain decimal signs/operators."""
    removed = set()
    for match in re.finditer(r"(?<=\w)-\s*\n\s*(?=\w)", text):
        removed.update(range(match.start(), match.end()))
    chars, positions = [], []
    for index, value in enumerate(text):
        if index in removed:
            continue
        for char in unicodedata.normalize("NFKC", value).casefold():
            decimal_point = (
                char == "."
                and 0 < index < len(text) - 1
                and text[index - 1].isdigit()
                and text[index + 1].isdigit()
            )
            if char.isalnum() or char in "√≥≤−+/" or decimal_point:
                chars.append(char)
                positions.append(index)
    return "".join(chars), positions


def resolve_evidence(
    questions: dict[str, Any], documents: list[ExtractedPaper]
) -> list[dict[str, Any]]:
    pages = {}
    for document in documents:
        position = 0
        for page in document.pages:
            if page.duplicate_of is not None:
                continue
            pages[(document.paper.arxiv_id, page.page_number)] = (position, page.text)
            position += len(page.text) + 1
    adaptations = []
    failures = []
    for question in questions["answerable"]:
        for unit in question["units"]:
            for alternative in unit["alternatives"]:
                for span in alternative:
                    offset, text = pages[(question["paper"], span["page"])]
                    target, positions = canonical(text)
                    quote = span["quote"]
                    # Same Table 4 header facts, now serialized in geometric row order.
                    if question["id"] == "H3" and quote.startswith("Model\nChinese\nCode"):
                        quote = quote.replace("Model\nChinese\nCode", "Chinese\nCode\nModel", 1)
                        adaptations.append(
                            {
                                "question": question["id"],
                                "page": span["page"],
                                "original": span["quote"],
                                "adapted": quote,
                                "reason": "Header row order follows PDF baselines; "
                                "labels, values and evidence rule unchanged.",
                            }
                        )
                    needle, _ = canonical(quote)
                    matches = list(re.finditer(re.escape(needle), target))
                    if len(matches) != 1:
                        failures.append(
                            {
                                "question": question["id"],
                                "page": span["page"],
                                "quote": quote,
                                "matches": len(matches),
                            }
                        )
                        continue
                    match = matches[0]
                    span["start_char"] = offset + positions[match.start()]
                    span["end_char"] = offset + positions[match.end() - 1] + 1
    if failures:
        raise ValueError(
            "Evidence alignment failed before retrieval:\n"
            + json.dumps(failures, ensure_ascii=False, indent=2)
        )
    return adaptations


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


def coverage(question: dict[str, Any], hits: list[SearchHit] | tuple[SearchHit, ...]) -> list[bool]:
    intervals = [
        (hit.char_start, hit.char_start + len(hit.text))
        for hit in hits
        if hit.arxiv_id == question["paper"] and hit.char_start is not None
    ]
    return [
        any(
            all(covered(span["start_char"], span["end_char"], intervals) for span in alternative)
            for alternative in unit["alternatives"]
        )
        for unit in question["units"]
    ]


def block_network(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("Network connections are disabled for this local evaluation")


def validate_records(
    records: dict[str, Any], documents: list[ExtractedPaper], tokenizer: Any
) -> dict[str, int]:
    pages, parents, papers = {}, {}, {}
    for doc in documents:
        position, parts = 0, []
        papers[doc.paper.arxiv_id] = doc.paper
        for page in doc.pages:
            if page.duplicate_of is not None:
                continue
            pages[(doc.paper.arxiv_id, page.page_number)] = (position, page.text)
            parts.append(page.text + "\n")
            position += len(page.text) + 1
        parents[doc.paper.arxiv_id] = "".join(parts)
    spans, starts, ends = 0, 0, 0
    for row in records.values():
        meta, text = row["metadata"], row["text"]
        paper = papers[meta["arxiv_id"]]
        assert (meta["paper_title"], meta["version"], meta["pdf_sha256"], meta["source_url"]) == (
            paper.title,
            paper.version,
            paper.sha256,
            paper.url,
        )
        parent = parents[paper.arxiv_id]
        a, b = meta["char_start"], meta["char_end"]
        assert parent[a:b] == text
        assert (
            len(tokenizer.encode(text, add_special_tokens=False, truncation=False, verbose=False))
            == meta["token_count"]
        )
        starts += int(a > 0 and parent[a - 1].isalnum() and parent[a].isalnum())
        ends += int(b < len(parent) and parent[b - 1].isalnum() and parent[b].isalnum())
        sources = json.loads(meta["source_spans_json"])
        assert sorted({s["page_number"] for s in sources}) == json.loads(meta["page_numbers_json"])
        for source in sources:
            spans += 1
            offset, page_text = pages[(paper.arxiv_id, source["page_number"])]
            left, right = source["start_char"], source["end_char"]
            assert 0 <= left < right <= len(text)
            assert page_text[a + left - offset : a + right - offset] == text[left:right]
    assert not starts and not ends, "Boundary chunks must not cut inside words or numbers"
    return {
        "chunks_checked": len(records),
        "source_spans_checked": spans,
        "word_interior_starts": starts,
        "word_interior_ends": ends,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--db-dir", type=Path, default=ROOT / "data/chroma-v2")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--max-context-tokens", type=int, default=4096)
    args = parser.parse_args()
    if args.max_context_tokens < 1:
        parser.error("--max-context-tokens must be positive")
    if (args.output / "results.csv").exists():
        parser.error("Output already contains results.csv; use a new experiment directory")
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    socket.socket.connect = block_network
    socket.socket.connect_ex = block_network
    pipeline = RetrievalPipeline(papers_dir=ROOT / "papers", db_dir=args.db_dir)
    documents = pipeline.extract()
    questions = copy.deepcopy(
        json.loads((BASELINE / "evidence-reviewed.json").read_text(encoding="utf-8"))
    )
    adaptations = resolve_evidence(questions, documents)
    write_json(args.output / "evidence.json", questions)
    write_json(args.output / "evidence-adaptations.json", adaptations)
    write_json(
        args.output / "extraction.json",
        [
            {
                "paper": doc.paper.arxiv_id,
                "issues": [asdict(issue) for issue in doc.issues],
                "pages": [asdict(page) for page in doc.pages],
            }
            for doc in documents
        ],
    )
    print("Evidence aligned before retrieval.", flush=True)
    if args.prepare_only:
        return
    model = pipeline.embedder
    rows, rankings, inspections = [], {}, {}
    for size, config in PRESETS.items():
        pipeline.config = config
        ingestion = pipeline.ingest()
        write_json(args.output / f"ingestion-{size}.json", ingestion)
        index = ChromaIndex(args.db_dir, pipeline.descriptor)
        raw = index.collection.get(include=["documents", "metadatas"])
        records = {
            identifier: {"text": text, "metadata": meta}
            for identifier, text, meta in zip(
                raw["ids"], raw["documents"], raw["metadatas"], strict=True
            )
        }
        write_json(args.output / f"chunks-{size}.json", records)
        inspections[str(size)] = {
            "chunks": len(records),
            "descriptor": pipeline.descriptor,
            "verification": validate_records(records, documents, model.tokenizer),
        }
        rankings[str(size)] = {}
        for question in questions["answerable"] + questions["unanswerable"]:
            qid, query = question["id"], question["query"]
            case = {"query": query, "rankings": {}, "cutoffs": {}}
            for strategy, method in (
                ("vector", "vector"),
                ("bm25", "bm25"),
                ("hybrid", "hybrid_rrf"),
            ):
                ranked = pipeline.search(query, strategy=strategy, top_k=50)
                case["rankings"][method] = [[hit.chunk_id, hit.score] for hit in ranked]
                case["cutoffs"][method] = {}
                for k in sorted({3, 5, 10, config.top_k}):
                    hits = pipeline.search(query, strategy=strategy, top_k=k)
                    context = select_context(
                        hits, model.tokenizer, max_tokens=args.max_context_tokens, query=query
                    )
                    assessment = assess_evidence(context.hits, infer_requirements(query))
                    detail = {
                        "ids": [hit.chunk_id for hit in hits],
                        "context_hits": [hit.to_dict() for hit in context.hits],
                        "context_tokens": context.token_count,
                        "assessment": asdict(assessment),
                    }
                    row = {
                        "size": size,
                        "method": method,
                        "k": k,
                        "question": qid,
                        "answerable": int("units" in question),
                        "complete": "",
                        "context_complete": "",
                        "refused": int(assessment.refused),
                        "context_tokens": context.token_count,
                        "context_chunks": len(context.hits),
                    }
                    if "units" in question:
                        units, context_units = (
                            coverage(question, hits),
                            coverage(question, context.hits),
                        )
                        detail.update(units=units, context_units=context_units)
                        row.update(
                            complete=int(all(units)), context_complete=int(all(context_units))
                        )
                    case["cutoffs"][method][str(k)] = detail
                    rows.append(row)
            rankings[str(size)][qid] = case
            print(f"{size} {qid} evaluated", flush=True)
        write_json(args.output / "rankings.json", rankings)
    with (args.output / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["size"], row["method"], row["k"])].append(row)
    summary = []
    baseline = json.loads((BASELINE / "summary-reviewed.json").read_text(encoding="utf-8"))
    for (size, method, k), values in sorted(groups.items()):
        positive = [row for row in values if row["answerable"]]
        negative = [row for row in values if not row["answerable"]]
        before = next(
            row for row in baseline if (row["size"], row["method"], row["k"]) == (size, method, k)
        )
        summary.append(
            {
                "size": size,
                "method": method,
                "k": k,
                "questions": len(positive),
                "baseline_complete": before["complete_questions"],
                "complete": sum(row["complete"] for row in positive),
                "baseline_context_complete": before["context_complete_questions"],
                "context_complete": sum(row["context_complete"] for row in positive),
                "false_refusals": sum(row["refused"] for row in positive),
                "unsupported_questions": len(negative),
                "unsupported_refusals": sum(row["refused"] for row in negative),
                "mean_context_tokens": sum(row["context_tokens"] for row in positive)
                / len(positive),
            }
        )
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "protocol.json",
        {
            "baseline": BASELINE.relative_to(ROOT).as_posix(),
            "max_context_tokens": args.max_context_tokens,
            "questions_sha256": hashlib.sha256(
                (BASELINE / "evidence-reviewed.json").read_bytes()
            ).hexdigest(),
            "source_sha256": {
                path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((ROOT / "src/retrieval").glob("*.py"))
            },
            "indexing": inspections,
            "limits": "Same 12 diagnostic questions and five unsupported questions; "
            "not held out. Coverage measures annotated evidence, not generated answer accuracy. "
            "Refusal is a literal-constraint check, not semantic entailment.",
        },
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
