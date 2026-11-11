"""Offline fixtures. Test vectors exercise plumbing, not semantic model quality."""

import hashlib
import re
import socket
from pathlib import Path

import numpy as np
import pymupdf
import pytest

from retrieval.catalog import PAPERS, file_sha256, validate_corpus
from retrieval.embeddings import LocalEmbedder
from retrieval.errors import EmbeddingError
from retrieval.extraction import extract_pdf
from retrieval.models import ExtractedPaper, PageText, PaperSpec, SectionSpan, content_hash


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", help="Use the cached MiniLM model")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-integration"):
        marker = pytest.mark.skip(reason="Pass --run-integration to use the pinned local model")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(marker)


@pytest.fixture(scope="session", autouse=True)
def no_network():
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must not open network connections")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", blocked)
        patch.setattr(socket.socket, "connect_ex", blocked)
        yield


class RegexTokenizer:
    """Simple offset-preserving test tokenizer, deliberately not a semantic model."""

    is_fast = True
    cls_token_id = 101
    sep_token_id = 102
    pad_token_id = 0
    pattern = re.compile(r"\w+|[^\w\s]")

    def __call__(self, text, **kwargs):
        matches = list(self.pattern.finditer(text))
        return {
            "input_ids": [self._id(match.group()) for match in matches],
            "offset_mapping": [match.span() for match in matches],
        }

    def _id(self, token):
        special = {"alpha": 11, "beta": 12, "gamma": 13}
        return special.get(token, 200 + int(hashlib.sha256(token.encode()).hexdigest()[:6], 16))

    def encode(self, text, **kwargs):
        return self(text)["input_ids"]

    def num_special_tokens_to_add(self, **kwargs):
        return 2


class TestEmbedder:
    __test__ = False
    descriptor = {"model": "test-only-bag-of-words-v1", "dimension": 8}

    def __init__(self):
        self.tokenizer = RegexTokenizer()
        self.calls = 0
        self.fail_on_call = None

    def embed(self, texts):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise EmbeddingError("Simulated embedding interruption")
        vectors = []
        keywords = ("attention", "transformer", "speech", "moshi", "chunking", "hierarchy")
        for text in texts:
            terms = text.lower().split()
            vector = np.array([terms.count(word) for word in keywords] + [0.1, 0.1])
            vectors.append((vector / np.linalg.norm(vector)).tolist())
        return vectors


@pytest.fixture
def tokenizer():
    return RegexTokenizer()


@pytest.fixture
def test_embedder():
    return TestEmbedder()


@pytest.fixture(scope="session")
def papers_dir():
    return Path(__file__).resolve().parents[2] / "papers"


@pytest.fixture(scope="session")
def supplied_documents(papers_dir):
    return [extract_pdf(paper, papers_dir) for paper in validate_corpus(papers_dir)]


@pytest.fixture(scope="session")
def local_model(no_network):
    return LocalEmbedder(batch_size=16)


@pytest.fixture
def pdf_factory(tmp_path):
    def create(pages, *, name="sample.pdf", toc=None):
        path = tmp_path / name
        with pymupdf.open() as document:
            for index, body in enumerate(pages):
                page = document.new_page()
                if body:
                    for line_index, line in enumerate(body.splitlines()):
                        page.insert_text((72, 100 + 20 * line_index), line, fontsize=11)
                page.insert_text((72, 820), str(index + 1), fontsize=10)
            if toc:
                document.set_toc(toc)
            document.save(path)
        return PaperSpec("Synthetic paper", "9999.00001", 1, name, file_sha256(path))

    return create


@pytest.fixture
def small_documents():
    texts = (
        "attention transformer alpha beta gamma delta epsilon zeta eta theta iota kappa",
        "speech moshi lambda mu nu xi omicron pi rho sigma tau upsilon",
        "chunking hierarchy phi chi psi omega one two three four five six",
    )
    documents = []
    for paper, text in zip(PAPERS, texts, strict=True):
        page = PageText(1, text, (SectionSpan(0, len(text), "Abstract"),), content_hash(text))
        documents.append(ExtractedPaper(paper, 1, (page,), ()))
    return documents
