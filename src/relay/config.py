"""Configuration without credentials in dataclass fields or report payloads."""

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from .errors import RelayError

DEFAULT_MODEL = "openai/gpt-oss-20b"


def environment_value(name: str, env_file: Path) -> str | None:
    # Do not mutate the process environment or expand values into other settings.
    values = dotenv_values(env_file, interpolate=False) if env_file.is_file() else {}
    return os.environ.get(name) or values.get(name)


def load_api_key(env_file: Path) -> str:
    key = environment_value("GROQ_API_KEY", env_file)
    if not key or not key.strip() or any(c.isspace() for c in key):
        raise RelayError("configuration", "Set a valid GROQ_API_KEY in the environment or .env.")
    return key


@dataclass(frozen=True)
class RelayConfig:
    model: str = DEFAULT_MODEL
    preset: int = 600
    strategy: str = "bm25"
    evidence_tokens: int = 3000
    prompt_token_budget: int = 24000
    model_context_tokens: int = 32768
    max_output_tokens: int = 2048
    planning_tokens: int = 768
    request_timeout: float = 40.0
    turn_timeout: float = 180.0
    max_tool_calls: int = 2
    max_question_chars: int = 2000
    max_stream_chars: int = 60000
    papers_dir: Path = Path("papers")
    db_dir: Path = Path("data/chroma-v2")
    model_cache: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not re.fullmatch(
            r"[A-Za-z0-9_./:-]{1,120}", self.model
        ):
            raise ValueError("model must be a nonempty provider model ID")
        for name in (
            "preset",
            "evidence_tokens",
            "prompt_token_budget",
            "model_context_tokens",
            "max_output_tokens",
            "planning_tokens",
            "max_tool_calls",
            "max_question_chars",
            "max_stream_chars",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.preset not in {300, 600, 900}:
            raise ValueError("preset must be 300, 600 or 900")
        if self.strategy not in {"vector", "bm25", "hybrid"}:
            raise ValueError("strategy must be vector, bm25 or hybrid")
        if self.max_tool_calls > 4:
            raise ValueError("max_tool_calls must be between 1 and 4")
        for name in ("request_timeout", "turn_timeout"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive finite number")
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if (
            self.prompt_token_budget + max(self.max_output_tokens, self.planning_tokens)
            > self.model_context_tokens
        ):
            raise ValueError("prompt budget plus reserved output exceeds model_context_tokens")

    @classmethod
    def from_env(cls, env_file: Path = Path(".env"), **overrides: object) -> "RelayConfig":
        model = environment_value("GROQ_MODEL", env_file) or DEFAULT_MODEL
        return cls(**{"model": model, **overrides})
