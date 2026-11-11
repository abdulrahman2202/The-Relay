import json
from types import SimpleNamespace

from relay.cli import main
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
