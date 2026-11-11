"""Local, pinned SentenceTransformer inference without silent truncation."""

import logging
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .config import MODEL_NAME, MODEL_REVISION
from .errors import EmbeddingError

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    tokenizer: Any
    descriptor: dict[str, Any]

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _load_model(cache_dir: Path | None) -> Any:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(0)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    return SentenceTransformer(
        MODEL_NAME,
        revision=MODEL_REVISION,
        cache_folder=str(cache_dir) if cache_dir else None,
        local_files_only=True,
        trust_remote_code=False,
        device="cpu",
        backend="torch",
    ).eval()


class LocalEmbedder:
    """Embed every token, pooling bounded windows for chunks longer than MiniLM's limit.

    Each window embedding is L2-normalized, averaged with content-token-count weights,
    then normalized again. Both queries and documents use this exact same procedure.
    Token IDs go directly to the SentenceTransformer forward pass, avoiding a lossy
    decode/re-tokenize step. No model files are downloaded by this class.
    """

    def __init__(self, *, batch_size: int = 16, cache_dir: Path | None = None) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        try:
            self.model = _load_model(cache_dir)
            self.tokenizer = self.model.tokenizer
            if not self.tokenizer.is_fast:
                raise EmbeddingError("A fast tokenizer with character offsets is required")
            max_sequence = min(
                self.model.max_seq_length,
                self.model[0].auto_model.config.max_position_embeddings,
            )
            special_count = self.tokenizer.num_special_tokens_to_add(pair=False)
            if special_count != 2 or any(
                token is None
                for token in (
                    self.tokenizer.cls_token_id,
                    self.tokenizer.sep_token_id,
                    self.tokenizer.pad_token_id,
                )
            ):
                raise EmbeddingError("Expected the pinned MiniLM BERT tokenizer's CLS/SEP tokens")
            self.window_tokens = max_sequence - special_count
            self.dimension = self.model.get_embedding_dimension()
        except Exception as exc:
            raise EmbeddingError(
                f"Cannot load {MODEL_NAME}@{MODEL_REVISION} from the local cache. "
                "Prepare the pinned model files first; see docs/rag.md. "
                f"Details: {exc}"
            ) from exc
        self.batch_size = batch_size
        self.descriptor = {
            "model": MODEL_NAME,
            "revision": MODEL_REVISION,
            "dimension": self.dimension,
            "window_tokens": self.window_tokens,
            "pooling": "token-weighted-normalized-windows-v1",
            "device": "cpu",
            "torch_threads": 1,
            "seed": 0,
        }
        logger.info("Loaded local MiniLM: %d content tokens/window", self.window_tokens)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("Embedding inputs must be nonempty strings")
        try:
            return self._embed(texts)
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"Local embedding failed: {exc}") from exc

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import torch
        from torch.nn.functional import normalize

        windows: list[tuple[int, list[int]]] = []
        for text_index, text in enumerate(texts):
            ids = self.tokenizer.encode(
                text, add_special_tokens=False, truncation=False, verbose=False
            )
            if not ids:
                raise EmbeddingError("Input contains no usable tokens")
            windows.extend(
                (text_index, ids[start : start + self.window_tokens])
                for start in range(0, len(ids), self.window_tokens)
            )
        # Accumulate in float64 to minimize sensitivity to batching/rounding.
        pooled = np.zeros((len(texts), self.dimension), dtype=np.float64)
        for start in range(0, len(windows), self.batch_size):
            batch = windows[start : start + self.batch_size]
            # Construct BERT's single-sequence inputs directly. Transformers 5 removed
            # prepare_for_model; decoding these IDs into strings would lose information.
            width = max(len(ids) for _, ids in batch) + 2
            input_ids = torch.full(
                (len(batch), width), self.tokenizer.pad_token_id, dtype=torch.long
            )
            attention_mask = torch.zeros_like(input_ids)
            for row, (_, ids) in enumerate(batch):
                sequence = [self.tokenizer.cls_token_id, *ids, self.tokenizer.sep_token_id]
                input_ids[row, : len(sequence)] = torch.tensor(sequence, dtype=torch.long)
                attention_mask[row, : len(sequence)] = 1
            with torch.inference_mode():
                output = self.model({"input_ids": input_ids, "attention_mask": attention_mask})[
                    "sentence_embedding"
                ]
                vectors = normalize(output, p=2, dim=1).cpu().numpy()
            if vectors.shape != (len(batch), self.dimension) or not np.isfinite(vectors).all():
                raise EmbeddingError("Model returned invalid window embeddings")
            if np.any(np.linalg.norm(vectors, axis=1) <= 0):
                raise EmbeddingError("Model returned zero or non-finite window embeddings")
            for (text_index, ids), vector in zip(batch, vectors, strict=True):
                pooled[text_index] += len(ids) * vector
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        if not np.isfinite(pooled).all() or np.any(norms <= 0):
            raise EmbeddingError("Model returned zero or non-finite embeddings")
        return (pooled / norms).astype(np.float32).tolist()
