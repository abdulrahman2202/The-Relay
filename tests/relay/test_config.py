from dataclasses import asdict

import pytest

from relay.budget import prompt_upper_bound
from relay.config import RelayConfig, load_api_key
from relay.errors import RelayError


def test_dotenv_model_and_key_are_read_without_exposing_key_in_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "GROQ_API_KEY=test-only-secret\nGROQ_MODEL=openai/gpt-oss-20b\n", encoding="utf-8"
    )
    config = RelayConfig.from_env(env)
    assert load_api_key(env) == "test-only-secret"
    assert config.model == "openai/gpt-oss-20b"
    assert "secret" not in repr(config) and "api_key" not in asdict(config)
    monkeypatch.setenv("GROQ_MODEL", "custom/test-model")
    assert RelayConfig.from_env(env).model == "custom/test-model"


def test_missing_key_has_clear_safe_error(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RelayError, match="GROQ_API_KEY"):
        load_api_key(tmp_path / "missing")


@pytest.mark.parametrize(
    "settings",
    [
        {"max_tool_calls": 10},
        {"request_timeout": float("nan")},
        {"request_timeout": False},
        {"preset": True},
        {"strategy": "remote"},
        {"model": ""},
        {"prompt_token_budget": 32768},
        {"max_output_tokens": 0},
    ],
)
def test_invalid_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        RelayConfig(**settings)


def test_prompt_guard_accounts_for_unicode_and_tools():
    messages = [{"role": "user", "content": "हैलो " * 100}]
    without_tools = prompt_upper_bound(messages, None)
    assert without_tools > len(messages[0]["content"].encode("utf-8"))
    assert (
        prompt_upper_bound(messages, [{"type": "function", "description": "x" * 500}])
        > without_tools
    )
