"""Rescore saved rankings using reviewed evidence; no index/embedding changes."""

import copy
import csv
import json
from collections import defaultdict

from run_audit import OUT, ROOT, check_preservation, covered_units, resolve_gold, write_json
from retrieval.pipeline import RetrievalPipeline


def main():
    questions = json.loads((OUT / "questions.json").read_text(encoding="utf-8"))
    review = json.loads((OUT / "annotation-review.json").read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in questions["answerable"]}
    for addition in review["additions"]:
        by_id[addition["question"]]["units"][addition["unit"]]["alternatives"].extend(addition["alternatives"])
    documents = RetrievalPipeline(papers_dir=ROOT / "papers").extract()
    resolve_gold(questions, documents)
    questions["annotation_review"] = "annotation-review.json"
    write_json("evidence-reviewed.json", questions)
    runs = json.loads((OUT / "rankings.json").read_text(encoding="utf-8"))
    rows, differences, reviewed = [], [], {}
    for size, cases in runs.items():
        records = json.loads((OUT / f"chunks-{size}.json").read_text(encoding="utf-8"))
        reviewed[size] = {}
        for qid, question in by_id.items():
            coverage = copy.deepcopy(cases[qid]["coverage"])
            for method, cutoffs in coverage.items():
                for k, data in cutoffs.items():
                    units = covered_units(question, data["ids"], records)
                    context_units = covered_units(question, data["context_ids"], records)
                    if units != data["units"]:
                        differences.append({"size": size, "question": qid, "method": method, "k": int(k),
                                            "before": data["units"], "after": units})
                    data["units"] = units
                    data["complete"] = all(units)
                    data["context_complete"] = all(context_units)
                    data["one_chunk_complete"] = any(all(covered_units(question, [i], records)) for i in data["ids"])
                    rows.append({"size": int(size), "method": method, "k": int(k), "question": qid,
                                 "kind": question["kind"], "complete": int(all(units)),
                                 "units_covered": sum(units), "units_total": len(units),
                                 "one_chunk_complete": int(data["one_chunk_complete"]),
                                 "context_complete": int(data["context_complete"]),
                                 "context_tokens": data["context_tokens"], "context_chunks": len(data["context_ids"]),
                                 "retrieved_tokens": data["retrieved_tokens"]})
            reviewed[size][qid] = coverage
    write_json("coverage-reviewed.json", reviewed)
    write_json("annotation-effects.json", differences)
    with (OUT / "coverage-reviewed.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["size"], row["method"], row["k"])].append(row)
    summary = []
    for (size, method, k), values in sorted(grouped.items()):
        record = {"size": size, "method": method, "k": k, "questions": len(values),
                  "complete_questions": sum(v["complete"] for v in values),
                  "context_complete_questions": sum(v["context_complete"] for v in values),
                  "one_chunk_complete_questions": sum(v["one_chunk_complete"] for v in values),
                  "mean_context_tokens": sum(v["context_tokens"] for v in values) / len(values),
                  "mean_context_chunks": sum(v["context_chunks"] for v in values) / len(values),
                  "mean_retrieved_tokens": sum(v["retrieved_tokens"] for v in values) / len(values)}
        summary.append(record)
        print(record)
    write_json("summary-reviewed.json", summary)
    preservation = check_preservation()
    write_json("preservation-after.json", preservation)
    assert preservation["unchanged"], preservation


if __name__ == "__main__":
    main()
