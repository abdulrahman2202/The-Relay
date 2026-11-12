import json
from types import SimpleNamespace

import pytest

from relay.cli import display_result, main
from relay.orchestrator import TurnResult


def test_interactive_terminal_supports_multiple_questions_and_exit(monkeypatch, capsys):
    asked, closed = [], []

    def ask(question, output):
        asked.append(question)
        output("The supplied papers do not provide enough evidence to answer that question.\n")
        return TurnResult(status="refused")

    assistant = SimpleNamespace(ask=ask, llm=SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr("relay.cli.build_assistant", lambda *a: assistant)
    prompts = iter(["first question", "second question", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))
    assert main([]) == 0
    assert asked == ["first question", "second question"] and closed == [True]
    assert "Goodbye." in capsys.readouterr().out


def test_json_failure_is_structured_and_has_nonzero_exit(monkeypatch, capsys):
    result = TurnResult(
        status="failed", error={"code": "rate_limit", "message": "Wait before retrying."}
    )
    assistant = SimpleNamespace(ask=lambda *a: result, llm=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr("relay.cli.build_assistant", lambda *a: assistant)
    assert main(["--question", "Test", "--json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed" and output["answer"] == ""


def failed_turn():
    return TurnResult(
        status="failed",
        error={"code": "citation_validation", "message": "The quotation was rejected."},
        displayed_characters=20,
        failure_diagnostics={
            "rejected_quote": "A rejected quotation from the model.",
            "source_id": "S2",
            "last_record": {"type": "done"},
            "accepted_claims": [{"text": "The table reports 28.4."}],
            "stream_suffix": "\\\nUnexpected tail.",
            "unsupported_numbers": ["41.0"],
            "answer_coverage": {
                "missing": ["first-position boundary probability"],
                "unrecognized": [],
            },
            "provider_body": "never display provider bodies",
        },
    )


def test_failure_diagnostics_are_hidden_by_default(capsys):
    display_result(failed_turn())
    output = capsys.readouterr().out
    assert "partial response above is incomplete" in output
    assert "Failure diagnostics" not in output
    assert "A rejected quotation" not in output and "Unexpected tail" not in output


def test_optional_diagnostics_show_only_retained_failure_details(capsys):
    display_result(failed_turn(), diagnostics=True)
    output = capsys.readouterr().out
    for expected in (
        "Rejected quotation",
        "Source ID",
        "Last valid claim",
        "28.4",
        "Malformed stream suffix",
        "Unexpected tail",
        "Unsupported numbers",
        "41.0",
        "Missing answer parts",
        "first-position boundary probability",
    ):
        assert expected in output
    assert "never display provider bodies" not in output


def test_diagnostics_redact_credentials_and_escape_terminal_controls(capsys):
    result = failed_turn()
    secret = "actual-private-client-key"
    unsafe = (
        f"{secret} gsk_fake_credential sk-fake-credential "
        'GROQ_API_KEY="other-private-key" password=private-password '
        'client_secret="secret with spaces" api key="human readable key" '
        "Authorization: Bearer private-bearer-token \x1b[2J"
    )
    result.failure_diagnostics["rejected_quote"] = unsafe
    result.failure_diagnostics["stream_suffix"] = unsafe
    result.failure_diagnostics["accepted_claims"][0]["text"] = unsafe
    result.failure_diagnostics["source_id"] = secret
    display_result(result, diagnostics=True, secrets=(secret,))
    output = capsys.readouterr().out
    for hidden in (
        secret,
        "gsk_fake_credential",
        "sk-fake-credential",
        "other-private-key",
        "private-password",
        "secret with spaces",
        "human readable key",
        "private-bearer-token",
        "\x1b",
    ):
        assert hidden not in output
    assert "[REDACTED]" in output
    assert r"\u001b" in output


def test_numeric_failure_can_show_candidate_quotes_and_source_ids(capsys):
    result = failed_turn()
    result.failure_diagnostics["rejected_quote"] = None
    result.failure_diagnostics["source_id"] = None
    result.failure_diagnostics["candidate_record"] = {
        "evidence": [{"source_id": "S1", "quote": "Transformer (big) | 28.4 | 41.8"}]
    }
    display_result(result, diagnostics=True)
    output = capsys.readouterr().out
    assert 'Candidate source ID: "S1"' in output
    assert "Candidate quotation" in output


def test_diagnostic_fields_are_bounded_and_optional(capsys):
    result = failed_turn()
    result.failure_diagnostics = {"stream_suffix": "x" * 10000}
    display_result(result, diagnostics=True)
    output = capsys.readouterr().out
    assert "[truncated]" in output and len(output) < 3000
    result.failure_diagnostics = None
    display_result(result, diagnostics=True)
    assert "No retained diagnostics" in capsys.readouterr().out
    result.status = "answered"
    display_result(result, diagnostics=True)
    assert "Failure diagnostics" not in capsys.readouterr().out


def test_diagnostics_flag_works_in_interactive_mode_without_exposing_client_key(
    monkeypatch, capsys
):
    secret = "client-key-without-a-provider-prefix"
    result = failed_turn()
    result.failure_diagnostics["stream_suffix"] = secret
    assistant = SimpleNamespace(
        ask=lambda *args: result,
        llm=SimpleNamespace(close=lambda: None, client=SimpleNamespace(api_key=secret)),
    )
    monkeypatch.setattr("relay.cli.build_assistant", lambda *args: assistant)
    prompts = iter(["question", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))
    assert main(["--diagnostics"]) == 0
    output = capsys.readouterr().out
    assert "Failure diagnostics" in output and "[REDACTED]" in output
    assert secret not in output


def test_json_output_and_text_diagnostics_are_mutually_exclusive():
    with pytest.raises(SystemExit) as error:
        main(["--question", "test", "--json", "--diagnostics"])
    assert error.value.code == 2
