"""The only executable model tool: an adapter to the existing local RAG module."""

import json
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from retrieval.catalog import PAPERS
from retrieval.config import PRESETS
from retrieval.context import ContextSelection, select_context
from retrieval.models import SearchHit
from retrieval.pipeline import RetrievalPipeline

from .config import RelayConfig
from .errors import RelayError

TOOL_NAME = "search_research_papers"


def has_controls(text: str) -> bool:
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in text)


def strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError("Nonfinite JSON value")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise RelayError("invalid_json", "The model returned invalid structured data.") from exc


def tool_schema(config: RelayConfig) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Search the three supplied research papers locally. Preserve all question "
                "constraints. Return bounded passages with source identifiers, paper titles, "
                "arXiv versions and physical PDF pages. Omit strategy and preset to use the "
                "configured defaults; if supplied they must match the configuration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": config.max_question_chars,
                    },
                    "strategy": {"type": "string", "enum": [config.strategy]},
                    "preset": {"type": "integer", "enum": [config.preset]},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    query: str
    strategy: str
    preset: int

    def message(self) -> dict[str, Any]:
        return {
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "arguments": json.dumps(
                    {"query": self.query, "strategy": self.strategy, "preset": self.preset}
                ),
            },
        }


def parse_tool_calls(message: dict[str, Any], config: RelayConfig) -> list[ToolCall]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise RelayError("missing_tool_call", "The model did not produce a research tool call.")
    if len(calls) > config.max_tool_calls:
        raise RelayError("tool_limit", "The model exceeded the allowed number of tool calls.")
    result = []
    seen = set()
    for call in calls:
        if not isinstance(call, dict) or call.get("type") != "function":
            raise RelayError("tool_arguments", "Expected a structured function call.")
        identifier, function = call.get("id"), call.get("function")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[\w-]{1,128}", identifier)
            or identifier in seen
        ):
            raise RelayError("tool_arguments", "Invalid or repeated tool call identifier.")
        if not isinstance(function, dict) or function.get("name") != TOOL_NAME:
            raise RelayError("unknown_tool", "The model requested an unavailable tool.")
        encoded = function.get("arguments")
        if not isinstance(encoded, str) or len(encoded) > 12000:
            raise RelayError(
                "tool_arguments", "Tool arguments exceed their permitted format or size."
            )
        args = strict_json(encoded)
        if (
            not isinstance(args, dict)
            or "query" not in args
            or not set(args) <= {"query", "strategy", "preset"}
        ):
            raise RelayError(
                "tool_arguments",
                "The research tool accepts query with optional strategy and preset only.",
            )
        query = args["query"]
        if (
            not isinstance(query, str)
            or not 1 <= len(query.strip()) <= config.max_question_chars
            or has_controls(query)
        ):
            raise RelayError(
                "tool_arguments",
                "The search query is empty, too long or contains control characters.",
            )
        strategy = args.get("strategy", config.strategy)
        preset = args.get("preset", config.preset)
        if strategy != config.strategy or type(preset) is not int or preset != config.preset:
            raise RelayError(
                "tool_arguments", "The model must use the configured retrieval strategy and preset."
            )
        seen.add(identifier)
        result.append(ToolCall(identifier, query.strip(), strategy, preset))
    return result


@dataclass(frozen=True)
class ToolExecution:
    call: ToolCall
    hits: tuple[SearchHit, ...]
    seconds: float
    error: RelayError | None = None


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    hit: SearchHit
    call_id: str

    def tool_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "paper_title": self.hit.paper_title,
            "arxiv_id": self.hit.arxiv_id,
            "version": self.hit.version,
            "pages": list(self.hit.pages),
            "source_url": self.hit.source_url,
            "text": self.hit.text,
        }


def validate_hit(hit: SearchHit) -> None:
    paper = next((p for p in PAPERS if p.arxiv_id == hit.arxiv_id), None)
    if paper is None or (paper.title, paper.version) != (hit.paper_title, hit.version):
        raise RelayError(
            "source_metadata", "Retrieved source identity does not match the supplied corpus."
        )
    if (
        not hit.text.strip()
        or not hit.sources
        or list(hit.pages) != sorted({s.page_number for s in hit.sources})
    ):
        raise RelayError(
            "source_metadata", "Retrieved source has missing text or page attribution."
        )
    if any(
        type(s.page_number) is not int
        or s.page_number < 1
        or not 0 <= s.start_char < s.end_char <= len(hit.text)
        for s in hit.sources
    ):
        raise RelayError("source_metadata", "Retrieved source spans are invalid.")


class ResearchTool:
    def __init__(self, config: RelayConfig, *, pipeline: RetrievalPipeline | None = None) -> None:
        self.config = config
        self.pipeline = (
            pipeline
            if pipeline is not None
            else RetrievalPipeline(
                papers_dir=config.papers_dir,
                db_dir=config.db_dir,
                config=PRESETS[config.preset],
                model_cache=config.model_cache,
            )
        )

    def execute(self, call: ToolCall) -> ToolExecution:
        start = time.perf_counter()
        try:
            hits = self.pipeline.search(call.query, strategy=call.strategy)
            for hit in hits:
                validate_hit(hit)
            return ToolExecution(call, tuple(hits), time.perf_counter() - start)
        except Exception:
            # A storage/model failure is not evidence that the papers lack an answer.
            error = RelayError(
                "retrieval_failed",
                "The local research index could not be queried. "
                "Check the cached model and ingest the matching preset.",
            )
            return ToolExecution(call, (), time.perf_counter() - start, error)

    def select(self, hits: list[SearchHit], question: str, max_tokens: int) -> ContextSelection:
        return select_context(
            hits, self.pipeline.embedder.tokenizer, max_tokens=max_tokens, query=question
        )
