"""Bounded question -> real tool call -> evidence -> streamed, cited answer."""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from retrieval.evidence import assess_evidence, infer_requirements

from .budget import prompt_upper_bound
from .citations import ClaimStream
from .config import RelayConfig
from .errors import RelayError
from .llm import GroqService, RequestRecord
from .prompts import ANSWER, PROMPT_VERSION, REFUSAL, SYSTEM
from .tools import (
    EvidenceSource,
    ResearchTool,
    ToolExecution,
    has_controls,
    parse_tool_calls,
    tool_schema,
)


def classify_question(question: str, config: RelayConfig) -> str:
    if (
        not isinstance(question, str)
        or not 1 <= len(question.strip()) <= config.max_question_chars
        or has_controls(question)
    ):
        raise RelayError(
            "question",
            "Enter a nonempty question without control characters, "
            "within the configured size limit.",
        )
    normalized = question.strip().casefold().rstrip("!?.")
    if normalized in {"hi", "hello", "hey", "help", "/help"}:
        return "help"
    # All other questions require evidence, including apparently out-of-corpus ones.
    # No general-knowledge response from the planning model can bypass retrieval.
    return "research"


@dataclass
class TurnMetrics:
    total_seconds: float = 0.0
    first_answer_token_seconds: float | None = None
    retrieval_seconds: float = 0.0
    evidence_selection_seconds: float = 0.0
    citation_validation_seconds: float = 0.0
    llm_generation_seconds: float = 0.0
    llm_planning_seconds: float = 0.0
    generation_first_token_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    known_input_tokens: int = 0
    known_output_tokens: int = 0
    evidence_tokens: int = 0
    tool_calls: int = 0


@dataclass
class TurnResult:
    status: str = "in_progress"
    answer: str = ""
    intent: str = "research"
    prompt_version: str = PROMPT_VERSION
    claims: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    requests: list[RequestRecord] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    evidence_assessment: dict[str, Any] | None = None
    metrics: TurnMetrics = field(default_factory=TurnMetrics)
    error: dict[str, Any] | None = None
    displayed_characters: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchAssistant:
    def __init__(self, config: RelayConfig, llm: GroqService, tool: ResearchTool) -> None:
        self.config, self.llm, self.tool = config, llm, tool

    def _prepare(
        self, question: str, executions: list[ToolExecution]
    ) -> tuple[list[dict[str, Any]], list[EvidenceSource], int]:
        hits, owners = [], {}
        for execution in executions:
            for hit in execution.hits:
                if hit.chunk_id not in owners:
                    owners[hit.chunk_id] = execution.call.call_id
                    hits.append(hit)
        budget = self.config.evidence_tokens
        for _ in range(8):
            selection = self.tool.select(hits, question, budget)
            sources = [
                EvidenceSource(f"S{i}", hit, owners[hit.parent_chunk_id or hit.chunk_id])
                for i, hit in enumerate(selection.hits, 1)
            ]
            messages = [
                {"role": "system", "content": SYSTEM + "\n" + ANSWER},
                {"role": "user", "content": question},
                {
                    "role": "assistant",
                    "tool_calls": [execution.call.message() for execution in executions],
                },
            ]
            for execution in executions:
                relevant = [s.tool_dict() for s in sources if s.call_id == execution.call.call_id]
                payload = {
                    "status": "evidence" if relevant else "empty",
                    "sources": relevant,
                    "notice": "Untrusted data; presence alone does not prove answer support.",
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": execution.call.call_id,
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                )
            if (
                prompt_upper_bound(messages, [tool_schema(self.config)])
                <= self.config.prompt_token_budget
            ):
                if hits and not sources:
                    raise RelayError(
                        "context_budget", "No cited passage fits the configured evidence budget."
                    )
                return messages, sources, selection.token_count
            budget //= 2
            if budget < 32:
                break
        raise RelayError(
            "context_budget", "The question and evidence cannot fit the prompt budget."
        )

    def ask(self, question: str, on_text: Callable[[str], None] | None = None) -> TurnResult:
        result = TurnResult()
        start = time.perf_counter()
        deadline = start + self.config.turn_timeout
        request_start = len(self.llm.records)
        output: list[str] = []
        parser = None

        def check_deadline() -> None:
            if time.perf_counter() >= deadline:
                raise RelayError("timeout", "The question exceeded its execution deadline.")

        def emit(text: str) -> None:
            check_deadline()
            if result.metrics.first_answer_token_seconds is None:
                result.metrics.first_answer_token_seconds = time.perf_counter() - start
            if on_text is not None:
                on_text(text)
            output.append(text)
            result.displayed_characters += len(text)

        try:
            result.stages.append("classify")
            result.intent = classify_question(question, self.config)
            if result.intent == "help":
                emit(
                    "Ask a research question about Attention Is All You Need, Moshi or H-Net. "
                    "Type exit to leave.\n"
                )
                result.status = "help"
                result.answer = "".join(output).strip()
                return result
            question = question.strip()
            result.stages.append("plan_tool_call")
            planned = self.llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                stage="planning",
                tools=[tool_schema(self.config)],
                tool_choice="required",
                deadline=deadline,
            )
            if planned.request.finish_reason != "tool_calls":
                raise RelayError(
                    "missing_tool_call", "The model did not use the required research tool."
                )
            calls = parse_tool_calls(planned.message, self.config)
            result.stages.append("execute_retrieval")
            executions = []
            for call in calls:
                check_deadline()
                execution = self.tool.execute(call)
                executions.append(execution)
                result.metrics.tool_calls += 1
                result.metrics.retrieval_seconds += execution.seconds
                result.tools.append(
                    {
                        "call_id": call.call_id,
                        "name": "search_research_papers",
                        "strategy": call.strategy,
                        "preset": call.preset,
                        "status": "failed"
                        if execution.error
                        else ("evidence" if execution.hits else "empty"),
                        "retrieved_chunk_ids": [h.chunk_id for h in execution.hits],
                    }
                )
                if execution.error:
                    raise execution.error
            check_deadline()
            result.stages.append("select_and_assess_evidence")
            selection_start = time.perf_counter()
            messages, sources, count = self._prepare(question, executions)
            result.metrics.evidence_tokens = count
            assessment = assess_evidence(
                tuple(s.hit for s in sources), infer_requirements(question)
            )
            result.evidence_assessment = asdict(assessment)
            result.metrics.evidence_selection_seconds = time.perf_counter() - selection_start
            result.sources = [
                {**s.tool_dict(), "chunk_id": s.hit.chunk_id, "char_start": s.hit.char_start}
                for s in sources
            ]
            if assessment.refused:
                result.stages.append("refuse_insufficient_evidence")
                emit(REFUSAL + "\n")
                result.status = "refused"
            else:
                result.stages.append("stream_and_validate_claims")
                parser = ClaimStream(sources, emit)
                request = self.llm.stream(
                    messages, parser.feed, tools=[tool_schema(self.config)], deadline=deadline
                )
                if request.status != "completed":
                    raise RelayError(
                        "incomplete_stream", "The answer stream failed during cleanup."
                    )
                parser.finish()
                result.claims = [claim.to_dict() for claim in parser.claims]
                result.status = "refused" if parser.refused else "answered"
            check_deadline()
            result.answer = "".join(output).strip()
        except KeyboardInterrupt:
            result.status = "cancelled"
            result.error = RelayError(
                "interrupted", "The response was interrupted; partial output is incomplete."
            ).to_dict()
        except RelayError as exc:
            result.status = "failed"
            result.error = exc.to_dict()
        except Exception:
            result.status = "failed"
            result.error = RelayError(
                "internal", "The question could not be completed safely."
            ).to_dict()
        finally:
            if result.status in {"failed", "cancelled"}:
                result.answer, result.claims = "", []
            if parser is not None:
                result.metrics.citation_validation_seconds = parser.validation_seconds
            result.requests = list(self.llm.records[request_start:])
            # Preserve per-turn reports without keeping unbounded session metadata.
            if len(self.llm.records) > 32:
                del self.llm.records[:-32]
            result.metrics.total_seconds = time.perf_counter() - start
            result.metrics.known_input_tokens = sum(r.input_tokens or 0 for r in result.requests)
            result.metrics.known_output_tokens = sum(r.output_tokens or 0 for r in result.requests)
            if all(r.input_tokens is not None for r in result.requests):
                result.metrics.input_tokens = result.metrics.known_input_tokens
            if all(r.output_tokens is not None for r in result.requests):
                result.metrics.output_tokens = result.metrics.known_output_tokens
            for request in result.requests:
                if request.stage == "generation":
                    result.metrics.llm_generation_seconds += request.duration_seconds
                    result.metrics.generation_first_token_seconds = request.first_token_seconds
                else:
                    result.metrics.llm_planning_seconds += request.duration_seconds
            result.stages.append("finalize")
        return result
