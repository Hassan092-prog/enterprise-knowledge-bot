"""
retriever.py — Orchestrates the full ingestion and retrieval pipeline.

WHAT THIS FILE DOES:
    Acts as the single entry point for two operations:

    1. INGESTION ORCHESTRATION — ingest_file(path)
       Wires together document_loader → chunker → vector_store
       so callers never need to manage three separate steps.

    2. RETRIEVAL WITH RE-RANKING — retrieve(query)
       Calls vector_store.search() to get candidates, then
       applies lightweight re-ranking and MMR diversity filtering
       to return a high-quality, non-redundant set of chunks.

WHY THIS FILE EXISTS (Facade Pattern):
    Without retriever.py, the Streamlit UI would need to know about
    and call four different modules in the right order. That couples
    the UI tightly to implementation details.

    retriever.py is a Facade — a simplified interface over a complex
    subsystem. The UI calls two clean methods:
        retriever.ingest_file(path)
        retriever.retrieve(query)
    ...and knows nothing about chunking, ChromaDB, or re-ranking.

RE-RANKING STRATEGY:
    We use a lightweight keyword-overlap scorer as our re-ranker.
    This improves on pure cosine similarity by rewarding chunks that
    contain the actual words from the user's query — not just chunks
    that are embedding-similar (which can be semantically close but
    lack the specific terms the user cares about).

    Production alternative: a cross-encoder model like
    cross-encoder/ms-marco-MiniLM-L-6-v2 from sentence-transformers.
    More accurate but requires a model download (~90MB).
    Our approach achieves significant improvement at zero extra cost.

MMR (Maximal Marginal Relevance):
    After re-ranking, we apply MMR to ensure diversity.
    MMR selects chunks one at a time, always choosing the next chunk
    that is:
      - Relevant to the query (high score)
      - Different from already-selected chunks (low overlap)
    This prevents returning 5 near-identical chunks that all say
    "revenue grew 23%" in slightly different ways.

DATA FLOW:
    INGESTION:
        file_path
            → load_document()       [document_loader.py]
            → chunk_documents()     [chunker.py]
            → add_documents()       [vector_store.py]
            → IngestResult(chunks_added, stats)

    RETRIEVAL:
        query_str
            → vector_store.search(k=20)     [get candidates]
            → _rerank(query, candidates)    [score by keyword overlap]
            → _mmr_filter(ranked, k=5)      [ensure diversity]
            → List[Document]                [top-k final results]
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import re

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from src.ingestion.chunker import chunk_documents, get_chunk_stats
from src.ingestion.document_loader import load_document
from src.logger import get_logger
from src.retrieval.vector_store import VectorStore
from src.config import RETRIEVAL_TOP_K

logger = get_logger(__name__)

# How many candidates to fetch before re-ranking
# We fetch 4x more than we need, then re-rank and filter down
_CANDIDATE_MULTIPLIER = 4


# ---------------------------------------------------------------------------
# Return types — structured results are better than raw tuples
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """
    Returned by ingest_file() to give the caller full visibility
    into what happened during ingestion.

    WHY A DATACLASS:
        Plain tuples like (3, 12, {...}) are hard to read.
        Dataclasses give named fields, type hints, and a clean repr.
        They are the modern Python replacement for NamedTuple in most cases.
    """
    source_filename: str       # e.g. "annual_report.pdf"
    chunks_added:   int        # new chunks stored (0 if already indexed)
    total_chunks:   int        # total chunks produced from this file
    stats:          dict       # full output of get_chunk_stats()
    already_existed: bool      # True if document was already in the store


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class Retriever:
    """
    Facade over the full RAG ingestion and retrieval pipeline.

    Instantiate once and reuse — VectorStore holds a persistent
    ChromaDB connection that should not be reopened on every query.

    Usage:
        retriever = Retriever()

        # Ingest a document
        result = retriever.ingest_file("data/uploads/report.pdf")
        print(f"Added {result.chunks_added} chunks")

        # Retrieve for a query
        docs = retriever.retrieve("What was the revenue growth?")
        for doc in docs:
            print(doc.metadata["source"], doc.page_content[:100])
    """

    def __init__(self) -> None:
        """
        Initialise the VectorStore and CrossEncoder.
        """
        self._store = VectorStore()
        logger.info("Loading CrossEncoder model...")
        self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Retriever ready — %d chunks indexed", self._store.get_stats()["total_chunks"])

    # ──────────────────────────────────────────────────────────────────
    # INGESTION ORCHESTRATION
    # ──────────────────────────────────────────────────────────────────

    def ingest_file(self, file_path: str | Path) -> IngestResult:
        """
        Full ingestion pipeline: parse → chunk → embed → store.

        This is the ONLY method the UI needs to call when a user
        uploads a document. All complexity is hidden here.

        Args:
            file_path: Path to the uploaded document.

        Returns:
            IngestResult with counts and stats.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file type is not supported.
        """
        file_path = Path(file_path)
        logger.info("Starting ingestion for: %s", file_path.name)

        # ── Step 1: Parse the document ──────────────────────────────
        documents = load_document(file_path)
        if not documents:
            logger.warning("No content extracted from %s", file_path.name)
            return IngestResult(
                source_filename=file_path.name,
                chunks_added=0,
                total_chunks=0,
                stats={},
                already_existed=False,
            )

        # ── Step 2: Chunk the document ──────────────────────────────
        chunks = chunk_documents(documents)
        stats  = get_chunk_stats(chunks)

        # ── Step 3: Check if already indexed ───────────────────────
        # list_sources() returns filenames currently in the vector store
        already_existed = file_path.name in self._store.list_sources()

        # ── Step 4: Store embeddings ────────────────────────────────
        # add_documents() is idempotent — skips existing chunk_ids
        chunks_added = self._store.add_documents(chunks)

        logger.info(
            "Ingestion complete: '%s' → %d/%d chunks added "
            "(already_existed=%s)",
            file_path.name, chunks_added, len(chunks), already_existed,
        )

        return IngestResult(
            source_filename=file_path.name,
            chunks_added=chunks_added,
            total_chunks=len(chunks),
            stats=stats,
            already_existed=already_existed,
        )

    def delete_document(self, source_filename: str) -> int:
        """
        Remove all chunks for a document from the vector store.

        Args:
            source_filename: Exact filename, e.g. "report.pdf"

        Returns:
            Number of chunks deleted.
        """
        deleted = self._store.delete_source(source_filename)
        logger.info("Deleted document '%s' (%d chunks)", source_filename, deleted)
        return deleted

    # ──────────────────────────────────────────────────────────────────
    # RETRIEVAL WITH RE-RANKING
    # ──────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        source_filter: Optional[str] = None,
        use_mmr: bool = True,
    ) -> List[Document]:
        """
        Retrieve the most relevant chunks for a query.

        Pipeline:
            1. Fetch k * CANDIDATE_MULTIPLIER candidates from ChromaDB
            2. Re-rank by keyword overlap score
            3. Apply MMR diversity filter (if use_mmr=True)
            4. Return top-k final results

        Args:
            query:         Natural language question from the user.
            k:             Number of chunks to return (default: RETRIEVAL_TOP_K).
            source_filter: If set, only search within this document.
            use_mmr:       Whether to apply MMR diversity filtering.

        Returns:
            List of Documents ordered by relevance, len <= k.
            Empty list if the vector store has no documents.
        """
        k = k or RETRIEVAL_TOP_K

        if self._store.is_empty():
            logger.warning("retrieve() called but vector store is empty")
            return []

        if not query.strip():
            logger.warning("retrieve() called with empty query")
            return []

        # ── Step 1: Fetch candidates ────────────────────────────────
        # Retrieve more than we need so re-ranking has room to work.
        # If top-k=5, we fetch 20 candidates then re-rank to best 5.
        n_candidates = min(
            k * _CANDIDATE_MULTIPLIER,
            self._store.get_stats()["total_chunks"],
        )

        # Hybrid Search: Get candidates from both Vector and BM25
        vector_candidates = self._store.search(
            query=query,
            k=n_candidates,
            source_filter=source_filter,
        )
        
        bm25_candidates = self._store.search_bm25(
            query=query,
            k=n_candidates,
            source_filter=source_filter,
        )
        
        # Combine using Reciprocal Rank Fusion (RRF)
        rrf_k = 60
        scores_map = {}
        docs_map = {}
        
        for rank, doc in enumerate(vector_candidates):
            chunk_id = doc.metadata.get("chunk_id", str(rank))
            scores_map[chunk_id] = scores_map.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs_map[chunk_id] = doc
            
        for rank, doc in enumerate(bm25_candidates):
            chunk_id = doc.metadata.get("chunk_id", str(rank + len(vector_candidates)))
            scores_map[chunk_id] = scores_map.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            if chunk_id not in docs_map:
                docs_map[chunk_id] = doc
                
        # Sort by RRF score and take top n_candidates
        candidates = []
        for chunk_id, _ in sorted(scores_map.items(), key=lambda x: x[1], reverse=True):
            candidates.append(docs_map[chunk_id])
            
        candidates = candidates[:n_candidates]

        if not candidates:
            return []

        # ── Step 2: Re-rank ─────────────────────────────────────────
        ranked = self._rerank(query, candidates)

        # ── Step 3: MMR diversity filter ────────────────────────────
        if use_mmr and len(ranked) > k:
            final = self._mmr_filter(ranked, k=k)
        else:
            final = ranked[:k]

        logger.info(
            "retrieve(): query='%s' → %d candidates → %d final results",
            query[:50], len(candidates), len(final),
        )
        return final

    # ──────────────────────────────────────────────────────────────────
    # RE-RANKING
    # ──────────────────────────────────────────────────────────────────

    def _rerank(
        self,
        query: str,
        candidates: List[Document],
    ) -> List[Document]:
        """
        Re-score and re-order candidates using a CrossEncoder model.
        """
        if not candidates:
            return []
            
        pairs = [[query, doc.page_content] for doc in candidates]
        scores = self._reranker.predict(pairs)
        
        for doc, score in zip(candidates, scores):
            doc.metadata["rerank_score"] = float(score)
            
        # Sort descending by rerank_score
        candidates.sort(key=lambda d: d.metadata.get("rerank_score", 0.0), reverse=True)
        return candidates

    # ──────────────────────────────────────────────────────────────────
    # MMR DIVERSITY FILTER
    # ──────────────────────────────────────────────────────────────────

    def _mmr_filter(
        self,
        ranked: List[Document],
        k: int,
        diversity_weight: float = 0.3,
    ) -> List[Document]:
        """
        Maximal Marginal Relevance — select k diverse, relevant chunks.

        ALGORITHM:
            1. Always select the highest-ranked chunk first.
            2. For each remaining slot:
               a. Score every remaining candidate as:
                  mmr_score = (1 - λ) * rerank_score
                            - λ * max_overlap_with_selected
               b. Select the candidate with the highest mmr_score.
            3. Repeat until k chunks are selected.

            λ (diversity_weight) controls the trade-off:
              λ = 0.0 → pure relevance (no diversity, same as top-k)
              λ = 0.5 → equal weight on relevance and diversity
              λ = 1.0 → pure diversity (ignores relevance scores)
              λ = 0.3 → slight diversity preference (our default)

        TEXT OVERLAP METRIC:
            We measure chunk similarity as word-level Jaccard similarity:
            |words_A ∩ words_B| / |words_A ∪ words_B|
            Simple, fast, and effective for detecting near-duplicate chunks.

        Args:
            ranked:           Documents sorted by rerank_score (best first).
            k:                Number of documents to select.
            diversity_weight: λ in the MMR formula (0.0 to 1.0).

        Returns:
            k Documents, balancing relevance and diversity.
        """
        if len(ranked) <= k:
            return ranked

        selected: List[Document] = []
        remaining = list(ranked)

        # Precompute word sets for overlap calculation
        def word_set(doc: Document) -> set:
            return set(re.sub(r'[^\w\s]', '', doc.page_content.lower()).split())

        word_sets = [word_set(d) for d in remaining]

        while len(selected) < k and remaining:
            if not selected:
                # First selection: always pick the top-ranked document
                selected.append(remaining.pop(0))
                word_sets.pop(0)
                continue

            # Compute MMR score for each remaining candidate
            best_score  = -float("inf")
            best_idx    = 0

            selected_words = [word_set(s) for s in selected]

            for i, (doc, doc_words) in enumerate(zip(remaining, word_sets)):
                relevance = doc.metadata.get("rerank_score", 0.0)

                # Max overlap with any already-selected chunk
                max_overlap = 0.0
                for sel_words in selected_words:
                    union = doc_words | sel_words
                    if union:
                        overlap = len(doc_words & sel_words) / len(union)
                        max_overlap = max(max_overlap, overlap)

                mmr_score = (
                    (1 - diversity_weight) * relevance
                    - diversity_weight * max_overlap
                )

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx   = i

            # Add the best MMR candidate to selected
            doc = remaining.pop(best_idx)
            doc.metadata["mmr_score"] = round(best_score, 4)
            word_sets.pop(best_idx)
            selected.append(doc)

        return selected

    # ──────────────────────────────────────────────────────────────────
    # CONVENIENCE METHODS
    # ──────────────────────────────────────────────────────────────────

    def get_knowledge_base_stats(self) -> dict:
        """Return stats about the current knowledge base."""
        return self._store.get_stats()

    def list_sources(self) -> List[str]:
        """Return sorted list of indexed document filenames."""
        return self._store.list_sources()

    def is_ready(self) -> bool:
        """Return True if the knowledge base has at least one document."""
        return not self._store.is_empty()
    def is_empty(self) -> bool:
        """Return True if no documents have been indexed yet."""
        return self._store.is_empty()