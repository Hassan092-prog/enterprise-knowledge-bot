"""
vector_store.py — ChromaDB interface for storing and searching embeddings.

WHAT THIS FILE DOES:
    Provides a clean class (VectorStore) that wraps ChromaDB.
    Handles all operations: adding chunks, searching by query,
    listing sources, deleting documents, and collection stats.

WHY A CLASS INSTEAD OF FUNCTIONS:
    The ChromaDB client and collection are stateful objects — they
    need to be initialised once and reused across calls. A class
    holds that state cleanly. This is the Repository pattern:
    hide all database complexity behind a simple interface.

CRITICAL RULE — SAME EMBEDDING MODEL EVERYWHERE:
    The model used here MUST match the model used in retrieval.
    We centralise it in config.py so there is zero chance of mismatch.
    If you ever change EMBEDDING_MODEL in config.py, you MUST delete
    your vectorstore and re-embed all documents from scratch.

DATA FLOW — INGESTION:
    List[Document] (chunks from chunker.py)
        → extract texts, ids, metadatas
        → OpenAI embedding API → List[List[float]]  (1536 dims each)
        → ChromaDB collection.add(ids, embeddings, documents, metadatas)
        → persisted to disk at data/vectorstore/

DATA FLOW — RETRIEVAL:
    query_text (str)
        → OpenAI embedding API → List[float]  (1536 dims)
        → ChromaDB collection.query(query_embeddings, n_results=k)
        → returns top-k chunks as List[Document] with metadata
"""

from pathlib import Path
from typing import List, Optional
from urllib import response

import chromadb
from chromadb.config import Settings
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
import re

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

from src.config import (
    CHROMA_COLLECTION_NAME,
    EMBEDDING_MODEL,
    LLM_PROVIDER,
    MISTRAL_API_KEY,
    OPENAI_API_KEY,
    RETRIEVAL_TOP_K,
    VECTORSTORE_DIR,
)
from src.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    """
    Wraps ChromaDB to provide a clean interface for the RAG pipeline.

    Usage:
        store = VectorStore()
        store.add_documents(chunks)          # after ingestion
        results = store.search("revenue?")   # during retrieval
        store.delete_source("report.pdf")    # document management

    WHY THIS DESIGN:
        Single responsibility — this class knows everything about
        ChromaDB and nothing about LLMs or the UI. If we swap
        ChromaDB for Pinecone, only this file changes.
    """

    def __init__(self) -> None:
        import os
        from dotenv import load_dotenv
        load_dotenv()

        self._client = chromadb.PersistentClient(
            path=str(VECTORSTORE_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        if LLM_PROVIDER == "mistral":
            from mistralai import Mistral
            api_key = os.environ.get("MISTRAL_API_KEY", "")
            self._mistral_client = Mistral(api_key=api_key)
            self._embeddings = None
        else:
            from langchain_openai import OpenAIEmbeddings
            self._mistral_client = None
            self._embeddings = OpenAIEmbeddings(
                model=EMBEDDING_MODEL,
                openai_api_key=OPENAI_API_KEY,
            )

        logger.info(
            "VectorStore ready — collection: '%s', model: '%s', "
            "existing chunks: %d",
            CHROMA_COLLECTION_NAME,
            EMBEDDING_MODEL,
            self._collection.count(),
        )

        self._bm25 = None
        self._bm25_docs = []
        self._build_bm25()

    def _build_bm25(self):
        """Rebuilds the BM25 index from all documents in ChromaDB."""
        if not BM25Okapi:
            return
            
        all_data = self._collection.get(include=["documents", "metadatas"])
        if not all_data["documents"]:
            self._bm25 = None
            self._bm25_docs = []
            return
            
        self._bm25_docs = [
            Document(page_content=doc, metadata=meta) 
            for doc, meta in zip(all_data["documents"], all_data["metadatas"])
        ]
        
        tokenized_corpus = [
            re.sub(r'[^\w\s]', '', doc.page_content.lower()).split() 
            for doc in self._bm25_docs
        ]
        self._bm25 = BM25Okapi(tokenized_corpus)
        logger.info("BM25 index built with %d chunks", len(self._bm25_docs))

    # ──────────────────────────────────────────────────────────────────
    # INGESTION
    # ──────────────────────────────────────────────────────────────────

    def add_documents(self, chunks: List[Document], user_id: Optional[int] = None, is_global: bool = False) -> int:
        """
        Embed a list of chunks and store them in ChromaDB.

        Handles duplicates gracefully — if a chunk_id already exists
        in the collection, we skip it (idempotent behaviour).
        This means re-uploading the same document does not create
        duplicate entries in the vector store.

        Args:
            chunks: Output of chunker.chunk_documents().

        Returns:
            Number of NEW chunks actually added (duplicates skipped).
        """
        if not chunks:
            logger.warning("add_documents() called with empty chunk list")
            return 0

        # ── Check for existing IDs to avoid duplicates ─────────────
        incoming_ids = [c.metadata["chunk_id"] for c in chunks]

        # Query which IDs already exist in the collection
        existing = self._collection.get(ids=incoming_ids, include=[])
        existing_ids = set(existing["ids"])

        # Filter to only new chunks
        new_chunks = [
            c for c in chunks
            if c.metadata["chunk_id"] not in existing_ids
        ]

        if not new_chunks:
            logger.info(
                "All %d chunks already indexed — skipping", len(chunks)
            )
            return 0

        if existing_ids:
            logger.info(
                "Skipping %d already-indexed chunks, adding %d new ones",
                len(existing_ids), len(new_chunks),
            )

        # ── Prepare data for ChromaDB ───────────────────────────────
        texts     = [c.page_content       for c in new_chunks]
        ids       = [c.metadata["chunk_id"] for c in new_chunks]
        
        # Inject user_id and is_global into metadata
        for c in new_chunks:
            if user_id is not None:
                c.metadata["user_id"] = user_id
            c.metadata["is_global"] = 1 if is_global else 0
            
        metadatas = [c.metadata            for c in new_chunks]

        # ── Generate embeddings via OpenAI API ──────────────────────
        # embed_documents() sends all texts in one batched API call.
        # Returns List[List[float]] — one 1536-dim vector per text.
        # This is the step that costs money (fractions of a cent per chunk).
        logger.info("Generating embeddings for %d chunks...", len(new_chunks))
        if self._mistral_client:
            response = self._mistral_client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=texts,
            )
            embeddings_list = [item.embedding for item in response.data]
        else:
            embeddings_list = self._embeddings.embed_documents(texts)
        logger.info("Embeddings generated successfully")

        # ── Store in ChromaDB ───────────────────────────────────────
        # ChromaDB stores the text, embedding, and metadata together.
        # The metadata is what we surface as citations in the UI.
        self._collection.add(
            ids=ids,
            embeddings=embeddings_list,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(
            "Added %d chunks to ChromaDB (collection total: %d)",
            len(new_chunks),
            self._collection.count(),
        )
        
        # Rebuild BM25 index after adding new documents
        self._build_bm25()
        
        return len(new_chunks)

    # ──────────────────────────────────────────────────────────────────
    # RETRIEVAL
    # ──────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        k: Optional[int] = None,
        source_filter: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Document]:
        """
        Find the k most semantically similar chunks to a query.

        Steps:
          1. Embed the query text using the same model as ingestion
          2. ChromaDB performs cosine similarity search over all vectors
          3. Return the top-k results as LangChain Documents

        Args:
            query: The user's natural language question.
            k: Number of chunks to return. Defaults to RETRIEVAL_TOP_K.
            source_filter: If provided, only search within this filename.
                           Example: "annual_report.pdf"

        Returns:
            List of Documents ordered by relevance (most relevant first).
            Each Document has page_content (the chunk text) and metadata
            (source, page, chunk_id) for citation generation.
        """
        if not query.strip():
            logger.warning("search() called with empty query")
            return []

        k = k or RETRIEVAL_TOP_K

        # ── Embed the query ─────────────────────────────────────────
        # CRITICAL: must use the SAME model as add_documents().
        # embed_query() returns a single vector: List[float]
        if self._mistral_client:
            response = self._mistral_client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=[query],
            )
            query_embedding = response.data[0].embedding
        else:
            query_embedding = self._embeddings.embed_query(query)

        # ── Build optional metadata filter ──────────────────────────
        # ChromaDB supports filtering by metadata fields.
        if user_id is not None:
            user_filter = {"$or": [{"user_id": user_id}, {"is_global": 1}]}
            if source_filter:
                where = {"$and": [{"source": source_filter}, user_filter]}
            else:
                where = user_filter
        else:
            where = {"source": source_filter} if source_filter else None

        # ── Query ChromaDB ──────────────────────────────────────────
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, self._collection.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        # ── Convert ChromaDB results → LangChain Documents ─────────
        # results["documents"][0] = list of chunk texts
        # results["metadatas"][0] = list of metadata dicts
        # results["distances"][0] = list of cosine distances (0=identical)
        # [0] because we sent one query — results are batched
        documents = []
        texts_     = results["documents"][0]
        metas      = results["metadatas"][0]
        distances  = results["distances"][0]

        for text, meta, distance in zip(texts_, metas, distances):
            # Convert cosine distance to similarity score (0 to 1)
            # distance=0 means identical → similarity=1.0
            # distance=2 means opposite  → similarity=0.0
            similarity = round(1 - distance / 2, 4)
            meta["similarity_score"] = similarity

            documents.append(
                Document(page_content=text, metadata=meta)
            )

        logger.info(
            "Search: '%s' → %d results (top score: %.4f)",
            query[:60],
            len(documents),
            documents[0].metadata["similarity_score"] if documents else 0,
        )
        return documents

    def search_bm25(
        self,
        query: str,
        k: Optional[int] = None,
        source_filter: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[Document]:
        """
        Find the k most relevant chunks using BM25 keyword matching.
        """
        if not self._bm25 or not query.strip():
            return []
            
        k = k or RETRIEVAL_TOP_K
        tokenized_query = re.sub(r'[^\w\s]', '', query.lower()).split()
        
        scores = self._bm25.get_scores(tokenized_query)
        
        scored_docs = []
        for score, doc in zip(scores, self._bm25_docs):
            if score > 0:
                is_global = doc.metadata.get("is_global") == 1
                if user_id is not None and doc.metadata.get("user_id") != user_id and not is_global:
                    continue
                if source_filter and doc.metadata.get("source") != source_filter:
                    continue
                # Make a copy so we don't mutate the cached doc
                scored_doc = Document(page_content=doc.page_content, metadata=doc.metadata.copy())
                scored_doc.metadata["bm25_score"] = float(score)
                scored_docs.append(scored_doc)
                
        scored_docs.sort(key=lambda d: d.metadata["bm25_score"], reverse=True)
        return scored_docs[:k]

    # ──────────────────────────────────────────────────────────────────
    # MANAGEMENT
    # ──────────────────────────────────────────────────────────────────

    def list_sources(self, user_id: Optional[int] = None) -> List[str]:
        """
        Return a list of unique source filenames currently indexed.

        Used by the UI to show the user which documents are in the
        knowledge base and to power the source filter dropdown.

        Returns:
            Sorted list of unique filenames, e.g.:
            ["annual_report.pdf", "glossary.txt", "products.csv"]
        """
        if self._collection.count() == 0:
            return []

        # Get all metadata from the collection
        if user_id is not None:
            where = {"$or": [{"user_id": user_id}, {"is_global": 1}]}
        else:
            where = None
        all_items = self._collection.get(where=where, include=["metadatas"])
        sources = {
            meta.get("source", "unknown")
            for meta in all_items["metadatas"]
        }
        return sorted(sources)

    def list_sources_by_type(self, user_id: Optional[int] = None) -> dict:
        """Return sources grouped by personal vs global."""
        if self._collection.count() == 0:
            return {"personal": [], "global": []}
            
        where = {"$or": [{"user_id": user_id}, {"is_global": 1}]} if user_id is not None else None
        all_items = self._collection.get(where=where, include=["metadatas"])
        
        personal = set()
        global_docs = set()
        for meta in all_items["metadatas"]:
            source = meta.get("source", "unknown")
            if meta.get("is_global") == 1:
                global_docs.add(source)
            else:
                personal.add(source)
                
        return {"personal": sorted(personal), "global": sorted(global_docs)}

    def delete_source(self, source_filename: str, user_id: Optional[int] = None) -> int:
        """
        Remove all chunks belonging to a specific source document.

        Called when the user wants to remove a document from the
        knowledge base and re-upload a newer version.

        Args:
            source_filename: Exact filename, e.g. "annual_report.pdf"

        Returns:
            Number of chunks deleted.
        """
        # Find all chunk IDs for this source
        where = {"source": source_filename}
        if user_id is not None:
            where["user_id"] = user_id
            
        results = self._collection.get(
            where=where,
            include=["metadatas"],
        )

        if not results["ids"]:
            logger.info("No chunks found for source: %s", source_filename)
            return 0

        count = len(results["ids"])
        self._collection.delete(ids=results["ids"])

        logger.info(
            "Deleted %d chunks for source '%s' (collection total: %d)",
            count,
            source_filename,
            self._collection.count(),
        )
        
        # Rebuild BM25 index after deleting documents
        self._build_bm25()
        
        return count

    def get_stats(self, user_id: Optional[int] = None) -> dict:
        """
        Return summary statistics about the vector store.

        Used by the UI dashboard and for debugging.

        Returns:
            {
                "total_chunks": 247,
                "total_sources": 5,
                "sources": ["report.pdf", "glossary.txt", ...]
            }
        """
        sources = self.list_sources(user_id=user_id)
        if user_id is not None:
            where = {"$or": [{"user_id": user_id}, {"is_global": 1}]}
        else:
            where = None
        total_chunks = len(self._collection.get(where=where, include=[])["ids"]) if where else self._collection.count()
        
        return {
            "total_chunks":  total_chunks,
            "total_sources": len(sources),
            "sources":       sources,
        }

    def is_empty(self) -> bool:
        """Return True if no documents have been indexed yet."""
        return self._collection.count() == 0