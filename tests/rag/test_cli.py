import json

from retrieval.cli import main


def test_extract_cli_writes_report_without_loading_a_model(papers_dir, tmp_path, capsys):
    output = tmp_path / "reports" / "extraction.json"
    assert main(["extract", "--papers-dir", str(papers_dir), "--output", str(output)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [document["page_count"] for document in data["documents"]] == [15, 66, 39]
    assert json.loads(output.read_text(encoding="utf-8")) == data


def test_cli_reports_invalid_configuration_without_traceback(capsys, caplog):
    assert main(["ingest", "--overlap", "300"]) == 1
    assert "overlap must be" in caplog.text
    assert "Traceback" not in capsys.readouterr().err


def test_cli_reports_missing_corpus(tmp_path, caplog):
    assert main(["extract", "--papers-dir", str(tmp_path / "missing")]) == 1
    assert "Papers directory does not exist" in caplog.text
