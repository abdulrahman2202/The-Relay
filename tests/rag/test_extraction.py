import pymupdf
import pytest

from retrieval.errors import ExtractionError
from retrieval.extraction import extract_pdf


def test_pages_sections_empty_pages_and_duplicates(tmp_path, pdf_factory):
    paper = pdf_factory(
        [
            "1 Introduction\nAlpha first paragraph.",
            None,
            "1 Introduction\nAlpha first paragraph.",
            "2 Methods\nBeta method.",
            "The method continues here.",
        ],
        toc=[[1, "Introduction", 1], [1, "Methods", 4]],
    )
    result = extract_pdf(paper, tmp_path)
    assert result.page_count == 5
    assert [page.page_number for page in result.pages] == [1, 3, 4, 5]
    assert [(issue.kind, issue.page_number) for issue in result.issues] == [
        ("empty_page", 2),
        ("duplicate_page", 3),
    ]
    assert result.pages[1].duplicate_of == 1
    assert result.pages[-1].sections[0].section == "2 Methods"
    assert result.paper.title == "Synthetic paper"
    assert result.paper.version == 1
    assert result.pages[0].text.startswith("1 Introduction")
    assert not result.pages[0].text.rstrip().endswith("1")


def test_unknown_section_is_not_invented(tmp_path, pdf_factory):
    paper = pdf_factory(["A paragraph without a recognizable section heading."])
    result = extract_pdf(paper, tmp_path)
    assert result.pages[0].sections[0].section is None


def test_bookmark_page_prevents_figure_labels_from_becoming_sections(tmp_path, pdf_factory):
    paper = pdf_factory(
        ["1\nIntroduction\nOpening paragraph.", "Methods\nA figure label.", "2\nMethods\nDetails."],
        toc=[[1, "Introduction", 1], [1, "Methods", 3]],
    )
    result = extract_pdf(paper, tmp_path)
    assert result.pages[0].sections[0].section == "1 Introduction"
    assert result.pages[1].sections[0].section == "1 Introduction"
    assert result.pages[2].sections[0].section == "2 Methods"


def test_all_empty_pdf_is_an_error(tmp_path, pdf_factory):
    paper = pdf_factory([None, None])
    with pytest.raises(ExtractionError, match="No extractable text.*OCR"):
        extract_pdf(paper, tmp_path)


def test_corrupt_pdf_is_an_error(tmp_path, pdf_factory):
    paper = pdf_factory(["Readable text"])
    (tmp_path / paper.filename).write_bytes(b"this is not a PDF")
    with pytest.raises(ExtractionError, match="Cannot extract"):
        extract_pdf(paper, tmp_path)


def test_page_extraction_failure_is_fatal(tmp_path, pdf_factory, monkeypatch):
    paper = pdf_factory(["Readable text"])

    def fail(*args):
        raise RuntimeError("broken page stream")

    monkeypatch.setattr("retrieval.extraction._page_lines", fail)
    with pytest.raises(ExtractionError, match="page 1: broken page stream"):
        extract_pdf(paper, tmp_path)


def test_password_protected_pdf_is_rejected(tmp_path, pdf_factory):
    paper = pdf_factory(["Readable text"])
    path = tmp_path / paper.filename
    with pymupdf.open(path) as document:
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader"
        )
    path.write_bytes(encrypted)
    with pytest.raises(ExtractionError, match="Encrypted PDF"):
        extract_pdf(paper, tmp_path)


def test_all_supplied_pages_and_known_sections(supplied_documents):
    assert [document.page_count for document in supplied_documents] == [15, 66, 39]
    expected = ["Scaled Dot-Product Attention", "Inner Monologue", "Dynamic Chunking"]
    for document, heading in zip(supplied_documents, expected, strict=True):
        assert len(document.pages) == document.page_count
        assert all(
            issue.kind in {"math_layout_warning", "table_layout_warning"}
            for issue in document.issues
        )
        sections = [span.section or "" for page in document.pages for span in page.sections]
        assert any(heading in section for section in sections)
        for page in document.pages:
            assert page.text.strip()
            assert all(0 <= s.start_char < s.end_char <= len(page.text) for s in page.sections)
            assert "arXiv:" not in page.text[:100]
