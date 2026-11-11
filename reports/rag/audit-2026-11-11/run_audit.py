"""Isolated audit experiment. Does not modify/import-patch the production implementation.

Run from the repository root with the existing virtual environment. All writes are
to this report directory or the scratch directory recorded in state.json. The
production database is never opened by Chroma during this audit.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import socket
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pymupdf

from retrieval.catalog import PAPERS
from retrieval.chunking import chunk_paper
from retrieval.config import PRESETS
from retrieval.embeddings import LocalEmbedder
from retrieval.index import ChromaIndex
from retrieval.models import SearchHit, SourceSpan, content_hash
from retrieval.pipeline import RetrievalPipeline

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
STOP = set("a an and are as at be been by did do does for from had has have how in into is it its of on or that the their there these this to was were what when where which who why will with would".split())
K_VALUES = (3, 5, 10)


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def blocked(*args, **kwargs):
    raise RuntimeError("Network connections are disabled for this local audit")


def check_preservation():
    before = json.loads((OUT / "preservation-before.json").read_text(encoding="utf-8"))
    changed = []
    for relative, expected in before.items():
        path = ROOT / relative
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if digest != expected:
            changed.append(relative)
    return {"files_checked": len(before), "changed_files": changed, "unchanged": not changed}


def resolve_gold(questions, documents):
    """Bind each factual unit to exact character spans before retrieving anything."""
    pages = {}
    texts = {}
    for document in documents:
        offset = 0
        parts = []
        for page in document.pages:
            if page.duplicate_of is not None:
                continue
            pages[(document.paper.arxiv_id, page.page_number)] = (offset, page.text)
            parts.append(page.text + "\n")
            offset += len(page.text) + 1
        texts[document.paper.arxiv_id] = "".join(parts)
    for question in questions["answerable"]:
        for unit in question["units"]:
            for alternative in unit["alternatives"]:
                for span in alternative:
                    offset, text = pages[(question["paper"], span["page"])]
                    matches = list(re.finditer(re.escape(span["quote"]), text))
                    if len(matches) != 1:
                        raise ValueError(f"Gold quote not unique: {question['id']} {span}: {len(matches)}")
                    span["start_char"] = offset + matches[0].start()
                    span["end_char"] = offset + matches[0].end()
    return texts, pages


def interval_covered(start, end, intervals):
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


def covered_units(question, ids, records):
    intervals = [
        (records[identifier]["metadata"]["char_start"], records[identifier]["metadata"]["char_end"])
        for identifier in ids
        if records[identifier]["metadata"]["arxiv_id"] == question["paper"]
    ]
    return [
        any(
            all(interval_covered(span["start_char"], span["end_char"], intervals) for span in alternative)
            for alternative in unit["alternatives"]
        )
        for unit in question["units"]
    ]


def lexical_tokens(text, dehyphenate=True):
    normalized = unicodedata.normalize("NFKC", text).casefold()
    if dehyphenate:
        normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)
    # Split quantities from units (160ms -> 160, ms), preserving decimal tokens.
    terms = re.findall(r"[^\W\d_]+|\d+(?:\.\d+)?", normalized, re.UNICODE)
    return [term for term in terms if term not in STOP]


class BM25:
    def __init__(self, records, *, dehyphenate=True):
        self.ids = list(records)
        self.dehyphenate = dehyphenate
        self.counts = [Counter(lexical_tokens(records[i]["text"], dehyphenate)) for i in self.ids]
        self.lengths = np.array([sum(count.values()) for count in self.counts], dtype=float)
        self.average = float(np.mean(self.lengths))
        self.df = Counter(term for count in self.counts for term in count)

    def rank(self, query):
        scores = np.zeros(len(self.ids), dtype=float)
        n = len(self.ids)
        for term in set(lexical_tokens(query, self.dehyphenate)):
            frequency = np.array([count[term] for count in self.counts], dtype=float)
            df = self.df[term]
            idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * self.lengths / self.average)
            scores += idf * frequency * 2.5 / denominator
        ranking = sorted(range(n), key=lambda i: (-scores[i], self.ids[i]))
        return [(self.ids[i], float(scores[i])) for i in ranking if scores[i] > 0]


def rrf(vector, lexical):
    scores = Counter()
    for ranking in (vector[:50], lexical[:50]):
        for rank, (identifier, _) in enumerate(ranking, 1):
            scores[identifier] += 1 / (60 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def citation_hit(identifier, records):
    record = records[identifier]
    meta = record["metadata"]
    return SearchHit(
        identifier, record["text"], meta["paper_title"], meta["arxiv_id"], meta["version"],
        tuple(json.loads(meta["page_numbers_json"])), tuple(json.loads(meta["sections_json"])),
        tuple(SourceSpan(**source) for source in json.loads(meta["source_spans_json"])), 0.0,
    )


def context_prefix(ids, records, tokenizer, budget=4096):
    """Apply the existing build_context policy without changing any chunk text."""
    context = ""
    kept = []
    for index, identifier in enumerate(ids, 1):
        hit = citation_hit(identifier, records)
        block = f"[{index}] {hit.citation}\n{hit.text}"
        candidate = f"{context}\n\n{block}" if context else block
        if len(tokenizer.encode(candidate, add_special_tokens=False, truncation=False)) > budget:
            break
        context = candidate
        kept.append(identifier)
    count = len(tokenizer.encode(context, add_special_tokens=False, truncation=False))
    return kept, count


def inspect_extraction(documents):
    output = []
    for document in documents:
        entry = {"paper": document.paper.arxiv_id, "version": document.paper.version,
                 "sha256": document.paper.sha256, "pages": document.page_count,
                 "issues": [asdict(issue) for issue in document.issues], "removed_lines": [],
                 "numeric_digit_count_before": 0, "numeric_digit_count_after": 0,
                 "control_characters": []}
        by_page = {page.page_number: page for page in document.pages}
        with pymupdf.open(ROOT / "papers" / document.paper.filename) as pdf:
            for number, page in enumerate(pdf, 1):
                retained = []
                for block in page.get_text("dict", sort=True)["blocks"]:
                    if block["type"] != 0:
                        continue
                    for line in block["lines"]:
                        text = unicodedata.normalize("NFKC", "".join(span["text"] for span in line["spans"]))
                        dx, dy = line.get("dir", (1, 0))
                        reason = None
                        if abs(dy) > abs(dx):
                            reason = "rotated"
                        elif text.strip().isdigit() and line["bbox"][1] > page.rect.height * 0.88:
                            reason = "bottom_integer"
                        elif line["bbox"][1] < page.rect.height * 0.09 and text.casefold().strip() == document.paper.title.casefold():
                            reason = "title_header"
                        if reason:
                            entry["removed_lines"].append({"page": number, "reason": reason, "text": text, "bbox": list(line["bbox"])})
                        else:
                            retained.append(text)
                extracted = by_page[number].text
                entry["numeric_digit_count_before"] += sum(ch.isdecimal() for ch in "".join(retained))
                entry["numeric_digit_count_after"] += sum(ch.isdecimal() for ch in extracted)
                controls = Counter(f"U+{ord(ch):04X}" for ch in extracted if ord(ch) < 32 and ch not in "\n\t\r")
                if controls:
                    entry["control_characters"].append({"page": number, "counts": dict(controls)})
        output.append(entry)
    return output


def window_diagnostic(model, query_vector, record):
    import torch

    text = record["text"]
    encoded = model.tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
    ids = encoded["input_ids"]
    offsets = encoded["offset_mapping"]
    result = []
    pooled = np.zeros(model.dimension, dtype=np.float64)
    for start in range(0, len(ids), model.window_tokens):
        end = min(start + model.window_tokens, len(ids))
        sequence = torch.tensor([[model.tokenizer.cls_token_id, *ids[start:end], model.tokenizer.sep_token_id]])
        with torch.inference_mode():
            vector = model.model({"input_ids": sequence, "attention_mask": torch.ones_like(sequence)})["sentence_embedding"][0].numpy()
        vector = vector / np.linalg.norm(vector)
        pooled += (end - start) * vector
        fragment = text[offsets[start][0]:offsets[end - 1][1]]
        result.append({"token_start": start, "token_end": end,
                       "query_cosine": float(np.dot(vector, query_vector)), "text": fragment,
                       "contains_160": "160" in fragment, "contains_200": "200" in fragment})
    pooled /= np.linalg.norm(pooled)
    normalized_text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    normalized_score = float(np.dot(model.embed([normalized_text])[0], query_vector))
    return {"windows": result, "pooled_query_cosine": float(np.dot(pooled, query_vector)),
            "dehyphenated_chunk_cosine_only": normalized_score,
            "ablation_note": "Single-candidate score diagnostic only; not a reranked corpus experiment."}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    preservation = check_preservation()
    if not preservation["unchanged"]:
        raise RuntimeError(f"Protected files changed before audit: {preservation}")
    state = json.loads((OUT / "state.json").read_text(encoding="utf-8"))
    scratch = Path(state["scratch"])
    if not scratch.resolve().is_relative_to((ROOT / ".cache").resolve()):
        raise RuntimeError("Scratch path is outside the audit cache")
    questions = json.loads((OUT / "questions.json").read_text(encoding="utf-8"))
    documents = RetrievalPipeline(papers_dir=ROOT / "papers").extract()
    full_text, page_offsets = resolve_gold(questions, documents)
    write_json("resolved-evidence.json", questions)
    protocol = {
        "question_file_sha256": hashlib.sha256((OUT / "questions.json").read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "positive_questions": len(questions["answerable"]), "negative_questions": len(questions["unanswerable"]),
        "chunk_sizes": [300, 600, 900], "overlap": 50, "cutoffs": list(K_VALUES),
        "paper_filter": None, "bm25": {"k1": 1.5, "b": 0.75, "stopwords": sorted(STOP), "join_line_hyphens": True},
        "rrf": {"constant": 60, "candidates_per_retriever": 50, "weights": [1, 1]},
        "metric": "Complete annotated evidence coverage: every required unit has at least one alternative fully covered by the union of returned source character intervals.",
        "limits": "Small diagnostic set, not held out. Table questions require column labels and named rows. No precision/nDCG or answer-generation accuracy is claimed. Corpus extraction fidelity is audited separately.",
    }
    write_json("protocol.json", protocol)
    write_json("extraction-inspection.json", inspect_extraction(documents))
    model = LocalEmbedder(batch_size=16)
    all_questions = questions["answerable"] + questions["unanswerable"]
    vectors = dict(zip((q["id"] for q in all_questions), model.embed([q["query"] for q in all_questions]), strict=True))
    rows, runs, inspections, diagnostics = [], {}, {}, {}
    for size, config in PRESETS.items():
        started = time.perf_counter()
        pipeline = RetrievalPipeline(papers_dir=ROOT / "papers", db_dir=scratch / "chroma", config=config, embedder=model)
        if size != 300:
            report = pipeline.ingest()
            write_json(f"audit-ingestion-{size}.json", report)
        index = ChromaIndex(scratch / "chroma", pipeline.descriptor)
        index.ensure_ready()
        stored = index.collection.get(include=["documents", "metadatas", "embeddings"])
        raw = {identifier: {"text": text, "metadata": meta, "vector": np.asarray(vector)}
               for identifier, text, meta, vector in zip(stored["ids"], stored["documents"], stored["metadatas"], stored["embeddings"], strict=True)}
        expected = []
        seen = set()
        for document in documents:
            for chunk in chunk_paper(document, model.tokenizer, config):
                key = (chunk.paper.document_id, content_hash(chunk.text))
                if key not in seen:
                    expected.append(chunk)
                    seen.add(key)
        records = {chunk.chunk_id: raw[chunk.chunk_id] for chunk in expected}
        problems = []
        if set(records) != set(raw):
            problems.append("Unexpected/missing IDs")
        interior_starts = interior_ends = 0
        for chunk in expected:
            row = records[chunk.chunk_id]
            if row["text"] != chunk.text or row["metadata"] != chunk.metadata():
                problems.append(chunk.chunk_id)
            parent = full_text[chunk.paper.arxiv_id]
            if parent[chunk.char_start:chunk.char_end] != chunk.text:
                problems.append("source mismatch: " + chunk.chunk_id)
            if chunk.char_start > 0 and parent[chunk.char_start - 1].isalnum() and parent[chunk.char_start].isalnum():
                interior_starts += 1
            if chunk.char_end < len(parent) and parent[chunk.char_end - 1].isalnum() and parent[chunk.char_end].isalnum():
                interior_ends += 1
        write_json(f"chunks-{size}.json", {identifier: {"text": row["text"], "metadata": row["metadata"]} for identifier, row in records.items()})
        inspections[str(size)] = {
            "collection": index.name, "fingerprint": index.fingerprint, "chunks": len(records),
            "by_paper": dict(Counter(record["metadata"]["arxiv_id"] for record in records.values())),
            "metadata_or_source_mismatches": problems, "word_interior_starts": interior_starts,
            "word_interior_ends": interior_ends, "ready": index.collection.metadata["ready"],
            "embedding_descriptor": model.descriptor,
            "preparation_seconds": time.perf_counter() - started,
        }
        if problems:
            raise RuntimeError(f"Stored content differs from current extraction: {problems}")
        lexical, lexical_raw = BM25(records), BM25(records, dehyphenate=False)
        ordered_ids = list(records)
        matrix = np.stack([records[identifier]["vector"] for identifier in ordered_ids]).astype(np.float64)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        config_runs = {}
        for question in all_questions:
            qid = question["id"]
            qvec = vectors[qid]
            start = time.perf_counter()
            vector_rank = [(hit.chunk_id, hit.score) for hit in index.search(qvec, top_k=50)]
            vector_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            lexical_rank = lexical.rank(question["query"])
            lexical_ms = (time.perf_counter() - start) * 1000
            raw_rank = lexical_raw.rank(question["query"])
            hybrid = rrf(vector_rank, lexical_rank)
            similarities = matrix @ np.asarray(qvec, dtype=np.float64)
            exact_rank = sorted(zip(ordered_ids, similarities.tolist(), strict=True), key=lambda item: (-item[1], item[0]))
            rankings = {"vector": vector_rank, "bm25": lexical_rank, "hybrid_rrf": hybrid, "bm25_raw": raw_rank}
            result = {"query": question["query"], "answerable": "units" in question,
                      "vector_top50_ms": vector_ms, "bm25_all_ms": lexical_ms,
                      "exact_cosine_top10": exact_rank[:10], "rankings": {name: ranking[:50] for name, ranking in rankings.items()},
                      "hnsw_top10_equals_exact": [i for i, _ in vector_rank[:10]] == [i for i, _ in exact_rank[:10]],
                      "native_k": config.top_k, "coverage": {}}
            for method, ranking in rankings.items():
                result["coverage"][method] = {}
                for k in sorted(set(K_VALUES + (config.top_k,))):
                    if method == "vector":
                        hits = index.search(qvec, top_k=k)
                        ids = [hit.chunk_id for hit in hits]
                        if ids != [identifier for identifier, _ in vector_rank[:k]]:
                            result.setdefault("hnsw_prefix_differences", {})[str(k)] = ids
                    else:
                        ids = [identifier for identifier, _ in ranking[:k]]
                    context_ids, context_tokens = context_prefix(ids, records, model.tokenizer)
                    cov = {"ids": ids, "context_ids": context_ids, "context_tokens": context_tokens,
                           "retrieved_tokens": sum(records[i]["metadata"]["token_count"] for i in ids)}
                    if "units" in question:
                        units = covered_units(question, ids, records)
                        context_units = covered_units(question, context_ids, records)
                        cov.update({"units": units, "complete": all(units), "context_complete": all(context_units),
                                    "one_chunk_complete": any(all(covered_units(question, [i], records)) for i in ids)})
                        rows.append({"size": size, "method": method, "k": k, "question": qid,
                                     "kind": question["kind"], "complete": int(all(units)),
                                     "units_covered": sum(units), "units_total": len(units),
                                     "one_chunk_complete": int(cov["one_chunk_complete"]),
                                     "context_complete": int(all(context_units)), "context_tokens": context_tokens,
                                     "context_chunks": len(context_ids), "retrieved_tokens": cov["retrieved_tokens"]})
                    result["coverage"][method][str(k)] = cov
            if "units" in question:
                result["all_corpus_units_covered"] = covered_units(question, ordered_ids, records)
                result["complete_single_chunk_exists"] = any(all(covered_units(question, [i], records)) for i in ordered_ids)
                result["exact_first_complete_prefix"] = next((k for k in range(1, len(exact_rank) + 1) if all(covered_units(question, [i for i, _ in exact_rank[:k]], records))), None)
            config_runs[qid] = result
            print(f"{size} {qid}: " + " | ".join(f"{m}=" + "/".join(str(int(result['coverage'][m][str(k)].get('complete', False))) for k in K_VALUES) for m in ("vector", "bm25", "hybrid_rrf")), flush=True)
        runs[str(size)] = config_runs
        latency = next(question for question in questions["answerable"] if question["id"] == "M1")
        candidates = {identifier for identifier in ordered_ids if all(covered_units(latency, [identifier], records))}
        candidates.add(config_runs["M1"]["rankings"]["vector"][0][0])
        diagnostics[str(size)] = {}
        for identifier in sorted(candidates):
            vector_ranking = config_runs["M1"]["rankings"]["vector"]
            exact = sorted(zip(ordered_ids, (matrix @ np.asarray(vectors["M1"])).tolist(), strict=True), key=lambda item: (-item[1], item[0]))
            diagnostics[str(size)][identifier] = {
                "pages": json.loads(records[identifier]["metadata"]["page_numbers_json"]),
                "text": records[identifier]["text"], "metadata": records[identifier]["metadata"],
                "full_answer_present": all(covered_units(latency, [identifier], records)),
                "hnsw_rank_within50": next((r for r, (i, _) in enumerate(vector_ranking, 1) if i == identifier), None),
                "exact_cosine_rank": next(r for r, (i, _) in enumerate(exact, 1) if i == identifier),
                "bm25_rank": next((r for r, (i, _) in enumerate(lexical.rank(latency["query"]), 1) if i == identifier), None),
                "hybrid_rank": next((r for r, (i, _) in enumerate(config_runs["M1"]["rankings"]["hybrid_rrf"], 1) if i == identifier), None),
                **window_diagnostic(model, vectors["M1"], records[identifier]),
            }
        config_runs["M1"]["paper_filtered_top10"] = [hit.to_dict() for hit in index.search(vectors["M1"], top_k=10, arxiv_id="2410.00037")]
        write_json("rankings.json", runs)
        write_json("index-inspection.json", inspections)
        write_json("moshi-diagnostics.json", diagnostics)
    with (OUT / "coverage.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    preservation = check_preservation()
    write_json("preservation-after.json", preservation)
    if not preservation["unchanged"]:
        raise RuntimeError(f"Protected file changes: {preservation}")
    print("AUDIT COMPLETE", preservation, flush=True)


if __name__ == "__main__":
    main()
