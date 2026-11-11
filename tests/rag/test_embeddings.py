from types import SimpleNamespace

import numpy as np
import pytest

from retrieval.embeddings import LocalEmbedder
from retrieval.errors import EmbeddingError


class WindowModel:
    max_seq_length = 8

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.seen = []

    def __getitem__(self, index):
        return SimpleNamespace(
            auto_model=SimpleNamespace(config=SimpleNamespace(max_position_embeddings=8))
        )

    def get_embedding_dimension(self):
        return 3

    def __call__(self, features):
        import torch

        output = []
        for row, mask in zip(features["input_ids"], features["attention_mask"], strict=True):
            content = row[mask.bool()].tolist()[1:-1]
            self.seen.append(content)
            assert len(content) <= 6
            output.append([content.count(11), content.count(12), content.count(13)])
        return {"sentence_embedding": torch.tensor(output, dtype=torch.float32)}


@pytest.fixture
def window_embedder(monkeypatch, tokenizer):
    model = WindowModel(tokenizer)
    monkeypatch.setattr("retrieval.embeddings._load_model", lambda cache: model)
    return LocalEmbedder(batch_size=2)


def test_long_inputs_include_tail_with_weighted_pooling(window_embedder):
    text = "alpha " * 6 + "beta " * 3
    vector = np.array(window_embedder.embed([text])[0])
    expected = np.array([6.0, 3.0, 0.0])
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(vector, expected, atol=1e-7)
    assert window_embedder.model.seen == [[11] * 6, [12] * 3]


def test_order_batch_size_and_normalization(window_embedder):
    texts = ["alpha " * 13, "beta gamma " * 10, "gamma"]
    first = np.array(window_embedder.embed(texts))
    window_embedder.batch_size = 1
    second = np.array(window_embedder.embed(texts))
    np.testing.assert_allclose(first, second, atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), 1, atol=1e-7)
    assert first[0].argmax() == 0
    assert first[2].argmax() == 2


def test_empty_and_invalid_embedding_inputs(window_embedder):
    assert window_embedder.embed([]) == []
    for value in ("", "   ", None):
        with pytest.raises(EmbeddingError, match="nonempty"):
            window_embedder.embed([value])
    with pytest.raises(EmbeddingError, match="zero or non-finite"):
        window_embedder.embed(["unrecognized"])


def test_missing_cache_has_actionable_error(monkeypatch):
    def missing(cache):
        raise OSError("No local snapshot")

    monkeypatch.setattr("retrieval.embeddings._load_model", missing)
    with pytest.raises(EmbeddingError, match="local cache.*Prepare the pinned model"):
        LocalEmbedder()


@pytest.mark.integration
def test_real_short_embeddings_match_sentence_transformers(local_model):
    texts = ["Scaled dot-product attention", "Moshi is a full-duplex speech model."]
    expected = local_model.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    np.testing.assert_allclose(local_model.embed(texts), expected, atol=1e-6)


@pytest.mark.integration
def test_real_long_embeddings_do_not_ignore_suffix(local_model):
    prefix = "attention transformer " * 200
    texts = [prefix + "speech dialogue " * 200, prefix + "hierarchical chunking " * 200]
    vectors = np.asarray(local_model.embed(texts))
    assert vectors.shape == (2, 384)
    assert np.isfinite(vectors).all()
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
    assert np.dot(vectors[0], vectors[1]) < 0.99
