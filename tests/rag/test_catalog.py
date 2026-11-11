from dataclasses import replace

import pytest

from retrieval.catalog import PAPERS, validate_corpus
from retrieval.errors import CorpusValidationError


def test_exact_supplied_identities_and_hashes(papers_dir):
    papers = validate_corpus(papers_dir)
    assert [(p.arxiv_id, p.version) for p in papers] == [
        ("1706.03762", 7),
        ("2410.00037", 1),
        ("2507.07955", 2),
    ]
    assert len({p.document_id for p in papers}) == 3
    assert all(len(p.sha256) == 64 for p in papers)


def test_missing_or_extra_papers_are_rejected(tmp_path):
    with pytest.raises(CorpusValidationError, match="exactly the three"):
        validate_corpus(tmp_path)
    for paper in PAPERS:
        (tmp_path / paper.filename).touch()
    (tmp_path / "unrequested.pdf").touch()
    with pytest.raises(CorpusValidationError, match="unexpected=.*unrequested"):
        validate_corpus(tmp_path)


def test_changed_pdf_is_rejected_before_parsing(tmp_path):
    for paper in PAPERS:
        (tmp_path / paper.filename).write_bytes(b"modified PDF")
    with pytest.raises(CorpusValidationError, match="SHA-256 mismatch"):
        validate_corpus(tmp_path)


def test_duplicate_pdf_bytes_are_detected(tmp_path, papers_dir):
    original = (papers_dir / PAPERS[0].filename).read_bytes()
    for paper in PAPERS:
        (tmp_path / paper.filename).write_bytes(original)
    with pytest.raises(CorpusValidationError, match="Duplicate PDF content"):
        validate_corpus(tmp_path)


def test_arxiv_version_is_verified_independently(tmp_path, pdf_factory, monkeypatch):
    specs = []
    for paper in PAPERS:
        generated = pdf_factory(
            [f"arXiv:{paper.arxiv_id}v99\nIncorrect version"], name=paper.filename
        )
        specs.append(replace(paper, sha256=generated.sha256))
    monkeypatch.setattr("retrieval.catalog.PAPERS", tuple(specs))
    with pytest.raises(CorpusValidationError, match="arXiv version stamp"):
        validate_corpus(tmp_path)


def test_missing_directory_is_clear(tmp_path):
    with pytest.raises(CorpusValidationError, match="does not exist"):
        validate_corpus(tmp_path / "absent")
