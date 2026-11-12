"""Interactive terminal entry point; answers are independent across questions."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .citations import Citation
from .config import RelayConfig, load_api_key
from .errors import RelayError
from .llm import GroqService
from .orchestrator import ResearchAssistant, TurnResult
from .tools import ResearchTool


def build_assistant(config: RelayConfig, env_file: Path) -> ResearchAssistant:
    service = GroqService(config, api_key=load_api_key(env_file))
    return ResearchAssistant(config, service, ResearchTool(config))


def _duration(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.3f} s"


def _diagnostic_value(value: str, secrets: tuple[str, ...]) -> str:
    """Bound and quote untrusted text; never emit terminal controls or credentials."""
    for secret in secrets:
        if secret:
            for encoded in (secret, json.dumps(secret, ensure_ascii=True)[1:-1]):
                value = value.replace(encoded, "[REDACTED]")
    value = re.sub(r"\b(?:gsk_|sk-)[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"(?i)(\b(?:bearer|basic)\s+)[^\s\"'\\,;{}\[\]]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"""(?ix)(\b[\w-]*(?:api[_ -]?key|secret(?:[_ -]?key)?|password|(?:access[_-]?)?token)
        \b["']?\s*[:=]\s*)
        (?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s"'\\,;{}\[\]]+)""",
        r"\1[REDACTED]",
        value,
    )
    if len(value) > 2000:
        value = value[:2000] + "... [truncated]"
    return json.dumps(value, ensure_ascii=True)


def display_failure_diagnostics(result: TurnResult, *, secrets: tuple[str, ...] = ()) -> None:
    details = result.failure_diagnostics
    print("\nFailure diagnostics:")
    if not isinstance(details, dict):
        print("- No retained diagnostics are available for this turn.")
        return
    fields = [
        ("Rejected quotation", details.get("rejected_quote")),
        ("Source ID", details.get("source_id")),
    ]
    candidate = details.get("candidate_record")
    if isinstance(candidate, dict) and isinstance(candidate.get("evidence"), list):
        for item in candidate["evidence"][:3]:
            if not isinstance(item, dict):
                continue
            if not details.get("source_id"):
                fields.append(("Candidate source ID", item.get("source_id")))
            if not details.get("rejected_quote"):
                fields.append(("Candidate quotation", item.get("quote")))
    accepted = details.get("accepted_claims")
    last = accepted[-1] if isinstance(accepted, list) and accepted else details.get("last_record")
    if isinstance(last, dict):
        fields.append(("Last valid claim", last.get("text")))
    fields.append(("Malformed stream suffix", details.get("stream_suffix")))
    numbers = details.get("unsupported_numbers")
    if isinstance(numbers, (list, tuple)):
        fields.append(("Unsupported numbers", ", ".join(n for n in numbers if isinstance(n, str))))
    coverage = details.get("answer_coverage")
    if isinstance(coverage, dict):
        for key, label in (
            ("missing", "Missing answer parts"),
            ("unrecognized", "Unrecognized question parts"),
        ):
            values = coverage.get(key)
            if isinstance(values, (list, tuple)):
                fields.append(
                    (label, "; ".join(value for value in values if isinstance(value, str)))
                )
    for label, value in fields:
        if isinstance(value, str) and value:
            print(f"- {label}: {_diagnostic_value(value, secrets)}")


def display_result(
    result: TurnResult, *, diagnostics: bool = False, secrets: tuple[str, ...] = ()
) -> None:
    if result.error:
        print(f"\nError [{result.error['code']}]: {result.error['message']}")
        if result.displayed_characters:
            print(
                "The partial response above is incomplete "
                "and was not recorded as a successful answer."
            )
        retry = result.error.get("retry_after_seconds")
        if retry is not None:
            print(f"Retry after at least {retry:g} seconds.")
    if diagnostics and result.status == "failed":
        display_failure_diagnostics(result, secrets=secrets)
    if result.status == "answered":
        references: dict[tuple[str, tuple[int, ...]], Citation] = {}
        for claim in result.claims:
            for raw in claim["citations"]:
                citation = Citation(**raw)
                references.setdefault((citation.source_id, tuple(citation.pages)), citation)
        print("\nSources:")
        for citation in references.values():
            print(f"- [{citation.source_id}] {citation.label}")
            print(f"  {citation.source_url}")
    metrics = result.metrics
    print(f"\nStatus: {result.status}")
    print("Metrics:")
    print(f"- Time to first answer token: {_duration(metrics.first_answer_token_seconds)}")
    print(f"- Generation stream first token: {_duration(metrics.generation_first_token_seconds)}")
    print(f"- Total response time: {_duration(metrics.total_seconds)}")
    print(f"- Retrieval: {_duration(metrics.retrieval_seconds)}")
    print(f"- Evidence selection: {_duration(metrics.evidence_selection_seconds)}")
    print(f"- LLM planning: {_duration(metrics.llm_planning_seconds)}")
    print(f"- LLM generation: {_duration(metrics.llm_generation_seconds)}")
    print(f"- Citation validation: {_duration(metrics.citation_validation_seconds)}")
    for label, value, known in (
        ("Input tokens", metrics.input_tokens, metrics.known_input_tokens),
        ("Output tokens", metrics.output_tokens, metrics.known_output_tokens),
    ):
        print(f"- {label}: {value if value is not None else f'unavailable (known: {known})'}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The Relay - AI Research Assistant")
    parser.add_argument("--question", help="Ask one question and exit")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="Return one result as JSON; requires --question"
    )
    output.add_argument(
        "--diagnostics", action="store_true", help="Show redacted diagnostics for failed turns"
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", help="Override GROQ_MODEL")
    parser.add_argument("--preset", type=int, choices=(300, 600, 900), default=600)
    parser.add_argument("--strategy", choices=("vector", "bm25", "hybrid"), default="bm25")
    parser.add_argument("--evidence-tokens", type=int, default=3000)
    parser.add_argument("--prompt-token-budget", type=int, default=24000)
    parser.add_argument("--model-context-tokens", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--request-timeout", type=float, default=40)
    parser.add_argument("--turn-timeout", type=float, default=180)
    parser.add_argument("--max-tool-calls", type=int, default=2)
    parser.add_argument("--papers-dir", type=Path, default=Path("papers"))
    parser.add_argument("--db-dir", type=Path, default=Path("data/chroma-v2"))
    parser.add_argument("--model-cache", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.json and args.question is None:
        parser.error("--json requires --question")
    overrides: dict[str, Any] = {
        name: getattr(args, name)
        for name in (
            "preset",
            "strategy",
            "evidence_tokens",
            "prompt_token_budget",
            "model_context_tokens",
            "max_output_tokens",
            "request_timeout",
            "turn_timeout",
            "max_tool_calls",
            "papers_dir",
            "db_dir",
            "model_cache",
        )
    }
    if args.model:
        overrides["model"] = args.model
    try:
        config = RelayConfig.from_env(args.env_file, **overrides)
        assistant = build_assistant(config, args.env_file)
    except (RelayError, ValueError, OSError):
        print(
            "Configuration error. Check .env, GROQ_API_KEY, GROQ_MODEL and the command options.",
            file=sys.stderr,
        )
        return 1
    try:

        def run(question: str) -> TurnResult:
            if not args.json:
                print("\nAssistant:", flush=True)
            result = assistant.ask(
                question, None if args.json else lambda text: print(text, end="", flush=True)
            )
            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=True, indent=2))
            else:
                api_key = getattr(getattr(assistant.llm, "client", None), "api_key", None)
                secrets = (api_key,) if isinstance(api_key, str) else ()
                display_result(result, diagnostics=args.diagnostics, secrets=secrets)
            return result

        if args.question is not None:
            result = run(args.question)
            return 130 if result.status == "cancelled" else int(result.status == "failed")
        print("The Relay - AI Research Assistant")
        print("Ask about the three supplied papers. Type exit to leave.\n")
        while True:
            try:
                question = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                return 0
            if question.casefold() in {"exit", "quit"}:
                print("Goodbye.")
                return 0
            if question:
                run(question)
    finally:
        try:
            assistant.llm.close()
        except Exception:
            print("The Groq client could not close cleanly.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
