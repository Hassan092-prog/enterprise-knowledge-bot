"""
chunker.py — Splits raw Documents into overlapping chunks.

WHAT THIS FILE DOES:
    Takes the large Documents produced by document_loader.py and
    splits them into smaller, overlapping pieces called "chunks".
    Each chunk becomes one entry in the vector database.

WHY CHUNKING IS NECESSARY:
    1. Embedding models have token limits (~8192 tokens max).
    2. Smaller chunks produce more precise retrieval results.
       You want to retrieve ONE relevant paragraph, not 50 pages.
    3. LLM context windows are limited — you can only inject
       a few chunks per query, so each one must be focused.

WHY OVERLAP:
    Imagine splitting this sentence at exactly 50 characters:
      Chunk A: "The company's revenue grew 23% year-over-year"
      Chunk B: "to $4.2 billion driven by the cloud division."
    Neither chunk alone answers "What was the revenue?"
    With 20-char overlap, Chunk B starts earlier and includes
    "grew 23% year-over-year to $4.2 billion" — complete context.

STRATEGY USED — Recursive Character Splitting:
    LangChain's RecursiveCharacterTextSplitter tries to split on:
      1. Paragraphs  (\n\n)   — preserves semantic boundaries
      2. Sentences   (. )     — preserves grammatical units
      3. Words       ( )      — preserves word integrity
      4. Characters  (any)    — last resort only
    It falls back to the next level only if the chunk is still too large.
    This is the industry default for most RAG systems.

DATA FLOW:
    List[Document] (large, raw)
        → RecursiveCharacterTextSplitter
        → List[Document] (small, overlapping, with enriched metadata)
"""

from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import CHUNK_SIZE, CHUNK_OVERLAP
from src.logger import get_logger

logger = get_logger(__name__)


def chunk_documents(documents: List[Document]) -> List[Document]:
    """
    Split a list of Documents into smaller overlapping chunks.

    Each output chunk inherits the metadata of its parent Document
    (source filename, page number, file type) PLUS a unique chunk_id
    and its position index within that source document.

    Args:
        documents: Raw Documents from document_loader.load_document().

    Returns:
        List of chunked Documents, ready for embedding.

    Example:
        A 10-page PDF with 500 words per page might produce ~50 chunks
        of ~150 words each, with 30-word overlap between adjacent chunks.
    """
    if not documents:
        logger.warning("chunk_documents() called with empty document list")
        return []

    # -----------------------------------------------------------------------
    # Build the splitter
    # -----------------------------------------------------------------------
    # chunk_size    : max characters per chunk (from config: 1000)
    # chunk_overlap : characters repeated between adjacent chunks (200)
    # length_function: we measure in characters, not tokens.
    #   WHY characters not tokens?
    #   Token counting requires calling tiktoken for every split — slow.
    #   Characters are a good-enough approximation: ~4 chars per token.
    #   1000 chars ≈ 250 tokens — well within embedding model limits.
    # add_start_index: adds a "start_index" field to metadata so you can
    #   trace exactly where in the original document this chunk came from.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        add_start_index=True,
        # These are the separators tried IN ORDER.
        # The splitter moves to the next only if the chunk is still too large.
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # -----------------------------------------------------------------------
    # Split all documents
    # -----------------------------------------------------------------------
    # split_documents() handles the list for us and preserves metadata
    chunks = splitter.split_documents(documents)

    # -----------------------------------------------------------------------
    # Enrich metadata — add chunk_id and position index
    # -----------------------------------------------------------------------
    # WHY chunk_id:
    #   When the LLM cites "annual_report.pdf, chunk 23", the user can
    #   inspect exactly which piece of text produced the answer.
    #   Also used as the unique ID when storing in ChromaDB.
    #
    # We group chunks by source so position numbers reset per document.
    source_counters: dict[str, int] = {}

    for chunk in chunks:
        source = chunk.metadata.get("source", "unknown")

        # Increment counter for this source document
        source_counters[source] = source_counters.get(source, 0) + 1
        position = source_counters[source]

        # Build a unique, human-readable chunk ID
        # Example: "annual_report.pdf_chunk_007"
        source_stem = source.rsplit(".", 1)[0]   # Remove file extension
        chunk.metadata["chunk_id"] = f"{source_stem}_chunk_{position:03d}"
        chunk.metadata["chunk_index"] = position

    # -----------------------------------------------------------------------
    # Log a summary
    # -----------------------------------------------------------------------
    total_input_docs = len(documents)
    total_chunks = len(chunks)
    avg_chunk_len = (
        sum(len(c.page_content) for c in chunks) // total_chunks
        if total_chunks else 0
    )

    logger.info(
        "Chunked %d document(s) → %d chunks (avg %d chars each, "
        "size=%d, overlap=%d)",
        total_input_docs,
        total_chunks,
        avg_chunk_len,
        CHUNK_SIZE,
        CHUNK_OVERLAP,
    )

    return chunks


def get_chunk_stats(chunks: List[Document]) -> dict:
    """
    Return summary statistics about a list of chunks.

    Useful for debugging and for displaying information in the UI
    after a user uploads a document.

    Args:
        chunks: Output of chunk_documents().

    Returns:
        Dictionary with counts, sizes, and source breakdown.

    Example return value:
        {
            "total_chunks": 47,
            "avg_chars": 892,
            "min_chars": 214,
            "max_chars": 1000,
            "sources": {
                "annual_report.pdf": 42,
                "glossary.txt": 5
            }
        }
    """
    if not chunks:
        return {"total_chunks": 0}

    lengths = [len(c.page_content) for c in chunks]

    # Count chunks per source document
    sources: dict[str, int] = {}
    for chunk in chunks:
        src = chunk.metadata.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    return {
        "total_chunks": len(chunks),
        "avg_chars":    sum(lengths) // len(lengths),
        "min_chars":    min(lengths),
        "max_chars":    max(lengths),
        "sources":      sources,
    }