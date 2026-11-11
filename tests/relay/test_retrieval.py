from types import SimpleNamespace

from relay.tools import ResearchTool, parse_tool_calls
from retrieval.catalog import PAPERS
from retrieval.config import PRESETS
from retrieval.index import ChromaIndex
from retrieval.models import Chunk
from retrieval.pipeline import RetrievalPipeline


def test_tool_uses_real_rag_and_chroma_without_reindexing(
    config, source, word_tokenizer, tool_message, tmp_path
):
    # Synthetic vectors exercise the adapter/storage contract. The unchanged RAG
    # integration suite separately tests real MiniLM inference on all three PDFs.
    embedder = SimpleNamespace(
        tokenizer=word_tokenizer, descriptor={"model": "phase3-test-only", "dimension": 3}
    )
    pipeline = RetrievalPipeline(db_dir=tmp_path / "chroma", config=PRESETS[600], embedder=embedder)
    index = ChromaIndex(pipeline.db_dir, pipeline.descriptor, create=True)
    text = source.hit.text
    count = len(word_tokenizer.encode(text))
    chunk = Chunk(
        source.hit.chunk_id,
        PAPERS[1],
        text,
        count,
        0,
        count,
        100,
        100 + len(text),
        source.hit.sources,
    )
    index.upsert([chunk], [[1.0, 0.0, 0.0]])
    index.finish({chunk.chunk_id})
    tool = ResearchTool(config, pipeline=pipeline)
    result = tool.execute(parse_tool_calls(tool_message, config)[0])
    assert result.error is None and len(result.hits) == 1
    assert result.hits[0].retrieval_method == "bm25"
    assert result.hits[0].pages == (1,) and result.hits[0].version == 1
    assert "200ms" in tool.select(list(result.hits), "Moshi latency", 300).text
    assert index.ids() == {chunk.chunk_id}
