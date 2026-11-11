"""Errors callers can handle without depending on vendor exceptions."""


class RagError(Exception):
    """Base error for this module."""


class CorpusValidationError(RagError):
    """A supplied PDF is missing, modified, or the wrong paper/version."""


class ExtractionError(RagError):
    """A PDF or page could not be read reliably."""


class EmbeddingError(RagError):
    """The local embedding model could not be loaded or used."""


class IndexingError(RagError):
    """The persisted index is unavailable, incomplete, or incompatible."""
