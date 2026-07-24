import pytest
from langchain_core.documents import Document
from src.ingestion.chunker import chunk_documents, get_chunk_stats

def test_chunk_documents_empty():
    assert chunk_documents([]) == []

def test_chunk_documents_metadata():
    # Provide a document large enough to split
    doc = Document(page_content="A " * 500, metadata={"source": "test.txt"})
    chunks = chunk_documents([doc])
    
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks, 1):
        assert chunk.metadata["source"] == "test.txt"
        assert chunk.metadata["chunk_index"] == i
        assert chunk.metadata["chunk_id"] == f"test_chunk_{i:03d}"

def test_get_chunk_stats():
    docs = [
        Document(page_content="Hello world", metadata={"source": "A.txt"}),
        Document(page_content="More text here", metadata={"source": "A.txt"}),
        Document(page_content="Other file", metadata={"source": "B.txt"}),
    ]
    
    stats = get_chunk_stats(docs)
    
    assert stats["total_chunks"] == 3
    assert stats["sources"]["A.txt"] == 2
    assert stats["sources"]["B.txt"] == 1
    assert stats["min_chars"] > 0
