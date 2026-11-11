"""Command-line interface for extraction, ingestion, and cited semantic search."""

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

from .config import PRESETS
from .errors import RagError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The Relay: local research-paper retrieval")
    parser.add_argument("--verbose", action="store_true", help="Show debug logging")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("extract", "ingest", "search", "retrieve"):
        command = commands.add_parser(name)
        command.add_argument("--papers-dir", type=Path, default=Path("papers"))
        command.add_argument("--output", type=Path, help="Also save the JSON result to this file")
        if name == "extract":
            continue
        command.add_argument("--db-dir", type=Path, default=Path("data/chroma-v2"))
        command.add_argument("--preset", type=int, choices=tuple(PRESETS), default=300)
        command.add_argument("--chunk-size", type=int, help="Override the preset's token count")
        command.add_argument("--overlap", type=int, help="Overlap in tokenizer tokens")
        command.add_argument("--top-k", type=int, help="Number of retrieved chunks")
        command.add_argument("--batch-size", type=int, default=16)
        command.add_argument("--model-cache", type=Path, help="Hugging Face hub cache directory")
        command.add_argument("--chunking", choices=("boundary", "fixed"), default="boundary")
        command.add_argument("--strategy", choices=("vector", "bm25", "hybrid"), default="vector")
        command.add_argument("--candidate-k", type=int, default=50)
        command.add_argument("--rrf-constant", type=int, default=60)
        command.add_argument("--bm25-k1", type=float, default=1.5)
        command.add_argument("--bm25-b", type=float, default=0.75)
        if name in {"search", "retrieve"}:
            command.add_argument("query")
            command.add_argument("--arxiv-id", help="Restrict results to one supplied paper")
        if name == "retrieve":
            command.add_argument("--max-context-tokens", type=int, default=4096)
            command.add_argument(
                "--require",
                action="append",
                default=[],
                help="Required evidence phrase (repeatable; AND semantics)",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        from .pipeline import RetrievalPipeline, extraction_summary

        if args.command == "extract":
            pipeline = RetrievalPipeline(papers_dir=args.papers_dir)
            result = {"documents": [extraction_summary(doc) for doc in pipeline.extract()]}
        else:
            overrides = {
                key: value
                for key in (
                    "chunk_size",
                    "overlap",
                    "top_k",
                    "batch_size",
                    "chunking",
                    "strategy",
                    "candidate_k",
                    "rrf_constant",
                    "bm25_k1",
                    "bm25_b",
                )
                if (value := getattr(args, key)) is not None
            }
            config = replace(PRESETS[args.preset], **overrides)
            pipeline = RetrievalPipeline(
                papers_dir=args.papers_dir,
                db_dir=args.db_dir,
                config=config,
                model_cache=args.model_cache,
            )
            if args.command == "ingest":
                result = pipeline.ingest()
            elif args.command == "retrieve":
                from .evidence import EvidenceRequirement

                requirements = tuple(
                    EvidenceRequirement(phrase, (phrase,), args.arxiv_id) for phrase in args.require
                )
                result = pipeline.retrieve(
                    args.query,
                    arxiv_id=args.arxiv_id,
                    max_tokens=args.max_context_tokens,
                    requirements=requirements,
                )
            else:
                hits = pipeline.search(args.query, arxiv_id=args.arxiv_id)
                result = {"query": args.query, "hits": [hit.to_dict() for hit in hits]}
        payload = json.dumps(result, indent=2, ensure_ascii=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    except (RagError, ValueError, OSError) as exc:
        logging.getLogger(__name__).error("%s", exc, exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
