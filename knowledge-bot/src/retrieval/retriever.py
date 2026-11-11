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
from typing import List, Optional, Callable, Union, BinaryIO, Any, Dict
import re
import math

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from src.ingestion.chunker import chunk_documents, get_chunk_stats
from src.ingestion.document_loader import load_document
from src.retrieval.summarizer import generate_document_summary
from src.logger import get_logger
from src.retrieval.vector_store import VectorStore
from src.config import RETRIEVAL_TOP_K

logger = get_logger(__name__)

def _sigmoid(x: float) -> float:
    """Normalize raw CrossEncoder logits into (0, 1) probability range for MMR."""
    try:
        return 1.0 / (1.0 + math.exp(-max(min(float(x), 20.0), -20.0)))
    except Exception:
        return 0.5

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

    def ingest_file(
        self,
        file_path: Union[str, Path, BinaryIO],
        user_id: Optional[int] = None,
        is_global: bool = False,
        tenant_id: Optional[int] = None,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        filename: Optional[str] = None,
    ) -> IngestResult:
        """
        Full ingestion pipeline: parse → chunk → embed → store.
        Partitioned by tenant_id and emits fine-grained progress callbacks.
        Supports local file paths and seekable BinaryIO streams (e.g. MinIO / S3).
        """
        if hasattr(file_path, "read"):
            source_filename = filename or getattr(file_path, "name", "document")
            source_stem = Path(source_filename).stem
            is_csv = source_filename.lower().endswith(".csv")
            documents = load_document(file_path, original_filename=source_filename)
        else:
            p = Path(file_path)
            source_filename = filename or p.name
            source_stem = Path(source_filename).stem
            is_csv = source_filename.lower().endswith(".csv")
            documents = load_document(p, original_filename=source_filename)

        logger.info("Starting ingestion for: %s (tenant=%s)", source_filename, tenant_id)

        if progress_callback:
            progress_callback("PARSING", 10, f"Loading document and extracting text from '{source_filename}'...")

        if not documents:
            logger.warning("No content extracted from %s", source_filename)
            if progress_callback:
                progress_callback("FAILED", 0, f"No readable content extracted from '{source_filename}'.")
            return IngestResult(
                source_filename=source_filename,
                chunks_added=0,
                total_chunks=0,
                stats={},
                already_existed=False,
            )

        # ── Step 2: Chunk the document ──────────────────────────────
        if progress_callback:
            progress_callback("CHUNKING", 30, f"Splitting document into semantic chunks...")
        chunks = chunk_documents(documents)
        
        # ── Step 2.5: Generate and add summary chunk ────────────────
        if not is_csv:
            if progress_callback:
                progress_callback("SUMMARIZING", 50, "Generating executive summary chunk via LLM...")
            summary_text = generate_document_summary(documents)
            summary_chunk = Document(
                page_content=f"EXECUTIVE SUMMARY OF {source_filename}:\n{summary_text}",
                metadata={
                    "source": source_filename,
                    "is_summary": True,
                    "chunk_id": f"{source_stem}_chunk_summary"
                }
            )
            chunks.append(summary_chunk)
        else:
            if progress_callback:
                progress_callback("SUMMARIZING", 50, "Bypassing LLM summary for structured tabular dataset...")
            
        stats  = get_chunk_stats(chunks)

        # ── Step 3: Check if already indexed within tenant ──────────
        already_existed = source_filename in self._store.list_sources(user_id=user_id, tenant_id=tenant_id)

        # ── Step 4: Store embeddings ────────────────────────────────
        if progress_callback:
            progress_callback("EMBEDDING", 70, f"Computing neural vector embeddings for {len(chunks)} chunks...")

        chunks_added = self._store.add_documents(
            chunks,
            user_id=user_id,
            is_global=is_global,
            tenant_id=tenant_id,
            progress_callback=progress_callback,
        )

        # ── Step 5: Knowledge Graph Extraction & Indexing (Global Org Corpus Only) ──
        try:
            from src.config import GRAPH_ENABLED
            if GRAPH_ENABLED and tenant_id is not None and is_global:
                if progress_callback:
                    progress_callback("GRAPH_INDEXING", 90, f"Extracting entities & relations for Knowledge Graph...")
                from src.graph.extractor import GraphExtractor
                from src.graph import get_graph_store
                full_text = "\n\n".join(d.page_content for d in documents)
                extractor = GraphExtractor()
                g_nodes, g_edges = extractor.extract_from_text(full_text, source_document=source_filename)
                if g_nodes or g_edges:
                    graph_store = get_graph_store()
                    graph_store.bulk_add(tenant_id=tenant_id, nodes=g_nodes, edges=g_edges)
        except Exception as graph_err:
            logger.warning("Notice: Knowledge graph extraction for '%s' encountered non-fatal issue: %s", source_filename, graph_err)

        if progress_callback:
            progress_callback("COMPLETED", 100, f"Successfully indexed {chunks_added} chunks.")

        logger.info(
            "Ingestion complete: '%s' → %d/%d chunks added (tenant=%s, already_existed=%s)",
            source_filename, chunks_added, len(chunks), tenant_id, already_existed,
        )

        return IngestResult(
            source_filename=source_filename,
            chunks_added=chunks_added,
            total_chunks=len(chunks),
            stats=stats,
            already_existed=already_existed,
        )

    def delete_document(
        self,
        source_filename: str,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> int:
        """
        Remove all chunks for a document from the vector store scoped to tenant,
        and cascade-purge corresponding entities from the knowledge graph for global documents.
        """
        deleted = self._store.delete_source(source_filename, user_id=user_id, tenant_id=tenant_id)
        if tenant_id is not None and user_id is None:
            try:
                from src.graph import get_graph_store
                get_graph_store().delete_document_entities(tenant_id=tenant_id, document_name=source_filename)
            except Exception as ge:
                logger.warning("Notice: Graph entity purge for '%s' notice: %s", source_filename, ge)
        logger.info("Deleted document '%s' (tenant=%s, %d chunks)", source_filename, tenant_id, deleted)
        return deleted

    def purge_user_personal_documents(self, user_id: int, tenant_id: int) -> int:
        """Purge all personal vector chunks for an offboarded user."""
        return self._store.delete_all_user_personal_chunks(user_id=user_id, tenant_id=tenant_id)

    # ──────────────────────────────────────────────────────────────────
    # RETRIEVAL WITH RE-RANKING
    # ──────────────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        user_id: Optional[int] = None,
        k: Optional[int] = None,
        source_filter: Optional[str] = None,
        use_mmr: bool = True,
        tenant_id: Optional[int] = None,
        trace: Optional[Any] = None,
        use_expansion: bool = True,
    ) -> List[Document]:
        """
        Retrieve the most relevant chunks for a query within the user's tenant.
        Instruments hybrid_retrieval and rerank_mmr spans when trace is provided.
        """
        k = k or RETRIEVAL_TOP_K

        if self._store.is_empty():
            logger.warning("retrieve() called but vector store is empty")
            return []

        if not query.strip():
            logger.warning("retrieve() called with empty query")
            return []

        # ── Step 1: Expand query ─────────────────────────────────────
        if trace and use_expansion:
            with trace.span(
                name="query_expansion",
                input_data={"query": query},
                metadata={"tenant_id": tenant_id}
            ) as exp_span:
                queries = self._expand_query(query)
                exp_span.metadata["variations_count"] = len(queries) - 1
                exp_span.end(output={"expanded_queries": queries})
        elif use_expansion:
            queries = self._expand_query(query)
        else:
            queries = [query]

        # ── Step 2: Fetch candidates (Hybrid Retrieval) ──────────────
        tenant_stats = self._store.get_stats(user_id=user_id, tenant_id=tenant_id)
        n_candidates = min(
            k * _CANDIDATE_MULTIPLIER,
            tenant_stats["total_chunks"] or 1,
        )

        def _do_hybrid_search():
            rrf_k = 60
            scores_map = {}
            docs_map = {}
            total_vec = 0
            total_bm25 = 0

            for q in queries:
                vector_candidates = self._store.search(
                    query=q,
                    k=n_candidates,
                    source_filter=source_filter,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                total_vec += len(vector_candidates)

                bm25_candidates = self._store.search_bm25(
                    query=q,
                    k=n_candidates,
                    source_filter=source_filter,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
                total_bm25 += len(bm25_candidates)

                # Combine using Reciprocal Rank Fusion (RRF)
                for rank, doc in enumerate(vector_candidates):
                    chunk_id = doc.metadata.get("chunk_id", str(rank))
                    scores_map[chunk_id] = scores_map.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
                    docs_map[chunk_id] = doc

                for rank, doc in enumerate(bm25_candidates):
                    chunk_id = doc.metadata.get("chunk_id", str(rank + len(vector_candidates)))
                    scores_map[chunk_id] = scores_map.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
                    if chunk_id not in docs_map:
                        docs_map[chunk_id] = doc

            cands = []
            for chunk_id, _ in sorted(scores_map.items(), key=lambda x: x[1], reverse=True):
                cands.append(docs_map[chunk_id])

            return cands[:n_candidates], total_vec, total_bm25

        if trace:
            with trace.span(
                name="hybrid_retrieval",
                input_data={"query": query, "source_filter": source_filter},
                metadata={"tenant_id": tenant_id, "source_filter": source_filter}
            ) as hr_span:
                candidates, n_vec, n_bm = _do_hybrid_search()
                hr_span.metadata["n_candidates"] = len(candidates)
                hr_span.metadata["vector_candidates"] = n_vec
                hr_span.metadata["bm25_candidates"] = n_bm
                hr_span.end(output={"candidates_count": len(candidates)})
        else:
            candidates, _, _ = _do_hybrid_search()

        if not candidates:
            return []

        # ── Step 3: Re-rank & MMR Diversity ──────────────────────────
        def _do_rerank_mmr():
            ranked = self._rerank(query, candidates)
            if use_mmr and len(ranked) > k:
                final = self._mmr_filter(ranked, k=k)
            else:
                final = ranked[:k]
            score_range = [
                float(final[0].metadata.get("rerank_score", 0.0)),
                float(final[-1].metadata.get("rerank_score", 0.0))
            ] if final else []
            return final, score_range

        if trace:
            with trace.span(
                name="rerank_mmr",
                input_data={"candidate_count": len(candidates)},
                metadata={"candidate_count": len(candidates), "k_final": k, "use_mmr": use_mmr}
            ) as rr_span:
                final, scores = _do_rerank_mmr()
                rr_span.metadata["score_range"] = scores
                rr_span.end(output={"final_count": len(final)})
        else:
            final, _ = _do_rerank_mmr()

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
        diversity_weight: float = 0.1,
    ) -> List[Document]:
        """
        Maximal Marginal Relevance — select k diverse, relevant chunks.

        ALGORITHM:
            1. Always select the highest-ranked chunk first.
            2. For each remaining slot:
               a. Score every remaining candidate as:
                  mmr_score = (1 - λ) * sigmoid(rerank_score)
                            - λ * max_overlap_with_selected
               b. Select the candidate with the highest mmr_score.
            3. Repeat until k chunks are selected.

            λ (diversity_weight) controls the trade-off:
              λ = 0.0 → pure relevance (no diversity, same as top-k)
              λ = 0.1 → relevance dominates; penalizes only near-duplicate redundancy (default)
              λ = 0.5 → equal weight on relevance and diversity

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
                raw_score = doc.metadata.get("rerank_score", 0.0)
                relevance = _sigmoid(raw_score)

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

    def get_knowledge_base_stats(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> dict:
        """Return stats about the knowledge base for a specific user and tenant."""
        return self._store.get_stats(user_id=user_id, tenant_id=tenant_id)

    def list_sources(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> List[str]:
        """Return sorted list of indexed document filenames for a user and tenant."""
        return self._store.list_sources(user_id=user_id, tenant_id=tenant_id)

    def list_sources_by_type(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> dict:
        """Return sources grouped by personal vs global for a user and tenant."""
        return self._store.list_sources_by_type(user_id=user_id, tenant_id=tenant_id)

    def is_empty(self) -> bool:
        """Return True if no documents have been indexed yet."""
        return self._store.is_empty()

    def heartbeat(self) -> int:
        """Return vector store server heartbeat timestamp."""
        return self._store.heartbeat()

    def _expand_query(self, query: str) -> List[str]:
        """
        Use the LLM to generate variations of the user's query to improve recall.
        Returns the original query plus up to 3 variations.
        """
        try:
            from langchain_core.prompts import ChatPromptTemplate
            from src.llm_factory import get_llm
            from langchain_core.output_parsers import StrOutputParser

            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert search assistant. Your task is to take a user's query and generate 3 different, synonymous search queries to improve retrieval recall in a vector database. Focus on resolving vocabulary mismatch. Output ONLY the 3 queries, one per line, without bullet points, numbers, or any other text."),
                ("human", "{query}")
            ])
            
            llm = get_llm(streaming=False)
            chain = prompt | llm | StrOutputParser()
            
            result = chain.invoke({"query": query})
            refusal_patterns = ["sorry", "can't help", "cannot help", "as an ai", "i am unable"]
            variations = [
                line.strip().lstrip("-*1234567890. ")
                for line in result.split("\n")
                if line.strip() and not any(p in line.lower() for p in refusal_patterns)
            ]
            
            # Add original query and ensure uniqueness
            all_queries = list(dict.fromkeys([query] + variations))
            logger.info(f"Query Expansion: '{query}' -> {all_queries[1:]}")
            return all_queries
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}. Falling back to original query.")
            return [query]