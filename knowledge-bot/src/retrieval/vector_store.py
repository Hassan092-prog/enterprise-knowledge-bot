"""
vector_store.py — ChromaDB interface for storing and searching embeddings (Hardened Multi-Tenant Edition).

WHAT THIS FILE DOES:
    Provides a clean class (VectorStore) that wraps ChromaDB.
    Handles all operations: adding chunks, searching by query,
    listing sources, deleting documents, and collection stats with
    strict tenant isolation (Postgres FK, ChromaDB tenant_id filter,
    per-tenant BM25 in-memory indices, and prefixed chunk_ids).
"""

from pathlib import Path
from typing import List, Optional, Dict, Tuple
import re

import chromadb
from chromadb.config import Settings
from langchain_core.documents import Document

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
    CHROMA_HOST,
    CHROMA_PORT,
)
from src.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    """
    Wraps ChromaDB to provide tenant-isolated search and indexing.
    """

    def __init__(self) -> None:
        import os
        from dotenv import load_dotenv
        load_dotenv()

        if CHROMA_HOST:
            logger.info("Connecting to remote ChromaDB at %s:%s", CHROMA_HOST, CHROMA_PORT)
            self._client = chromadb.HttpClient(
                host=CHROMA_HOST,
                port=CHROMA_PORT,
                settings=Settings(anonymized_telemetry=False),
            )
        else:
            logger.info("Using local PersistentClient ChromaDB at %s", VECTORSTORE_DIR)
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
            self._local_embedder = None
        elif LLM_PROVIDER == "groq":
            from sentence_transformers import SentenceTransformer
            self._mistral_client = None
            self._embeddings = None
            self._local_embedder = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Loaded local embedding model: %s", EMBEDDING_MODEL)
        else:
            from langchain_openai import OpenAIEmbeddings
            self._mistral_client = None
            self._local_embedder = None
            self._embeddings = OpenAIEmbeddings(
                model=EMBEDDING_MODEL,
                openai_api_key=OPENAI_API_KEY,
            )

        logger.info(
            "VectorStore ready — collection: '%s', model: '%s', existing chunks: %d",
            CHROMA_COLLECTION_NAME,
            EMBEDDING_MODEL,
            self._collection.count(),
        )

        # Per-tenant BM25 index mapping: tenant_id -> (BM25Okapi, List[Document])
        self._bm25_indices: Dict[int, Tuple[BM25Okapi, List[Document]]] = {}
        self._backfill_legacy_chunks(1)
        self._build_all_bm25()

    def _backfill_legacy_chunks(self, default_tenant_id: int = 1):
        """
        Backfill any legacy chunks stored before multi-tenancy was enabled.
        Ensures metadata has tenant_id=1 and is_global=1.
        """
        try:
            if self._collection.count() == 0:
                return

            all_data = self._collection.get(include=["metadatas"])
            ids_to_update = []
            updated_metadatas = []

            for chunk_id, meta in zip(all_data.get("ids", []), all_data.get("metadatas", [])):
                if meta is None:
                    meta = {}
                if "tenant_id" not in meta or meta.get("tenant_id") is None:
                    meta["tenant_id"] = default_tenant_id
                    if "is_global" not in meta:
                        meta["is_global"] = 1
                    ids_to_update.append(chunk_id)
                    updated_metadatas.append(meta)

            if ids_to_update:
                self._collection.update(
                    ids=ids_to_update,
                    metadatas=updated_metadatas
                )
                logger.info("Backfilled %d legacy chunks with tenant_id=%d", len(ids_to_update), default_tenant_id)
        except Exception as e:
            logger.warning("Legacy ChromaDB backfill notice: %s", e)

        # Migrate root upload files into tenant_1 folder
        try:
            from src.config import UPLOAD_DIR, get_tenant_upload_dir
            import shutil
            t1_dir = get_tenant_upload_dir(default_tenant_id)
            if UPLOAD_DIR.exists():
                for item in UPLOAD_DIR.iterdir():
                    if item.is_file():
                        target = t1_dir / item.name
                        if not target.exists():
                            shutil.copy2(str(item), str(target))
                            logger.info("Migrated legacy upload file '%s' into tenant_%d folder", item.name, default_tenant_id)
        except Exception as e:
            logger.warning("Legacy filesystem migration notice: %s", e)

    def _build_bm25_for_tenant(self, tenant_id: int):
        """Build or rebuild BM25 index strictly for a specific tenant."""
        if not BM25Okapi:
            return

        all_data = self._collection.get(
            where={"tenant_id": tenant_id},
            include=["documents", "metadatas"]
        )

        docs = []
        if all_data and all_data.get("documents"):
            for doc, meta in zip(all_data["documents"], all_data["metadatas"]):
                docs.append(Document(page_content=doc, metadata=meta or {}))

        if not docs:
            self._bm25_indices.pop(tenant_id, None)
            return

        tokenized_corpus = [
            re.sub(r'[^\w\s]', '', doc.page_content.lower()).split()
            for doc in docs
        ]
        self._bm25_indices[tenant_id] = (BM25Okapi(tokenized_corpus), docs)
        logger.info("BM25 index built for tenant %d with %d chunks", tenant_id, len(docs))

    def _build_all_bm25(self):
        """Scan ChromaDB on startup and build per-tenant BM25 indices."""
        if not BM25Okapi:
            return
        if self._collection.count() == 0:
            return

        all_data = self._collection.get(include=["metadatas"])
        tenant_ids = set()
        for meta in all_data.get("metadatas", []):
            if meta and "tenant_id" in meta:
                try:
                    tenant_ids.add(int(meta["tenant_id"]))
                except (ValueError, TypeError):
                    tenant_ids.add(1)
            else:
                tenant_ids.add(1)

        for tid in tenant_ids:
            self._build_bm25_for_tenant(tid)

    # ──────────────────────────────────────────────────────────────────
    # INGESTION
    # ──────────────────────────────────────────────────────────────────

    def add_documents(
        self,
        chunks: List[Document],
        user_id: Optional[int] = None,
        is_global: bool = False,
        tenant_id: Optional[int] = None,
    ) -> int:
        """
        Embed a list of chunks and store them in ChromaDB with tenant isolation.
        Prefixes chunk_id with `t{tenant_id}_` to avoid cross-tenant deduplication collisions.
        """
        if not chunks:
            logger.warning("add_documents() called with empty chunk list")
            return 0

        tid = tenant_id if tenant_id is not None else 1

        # Prefix chunk IDs with tenant_id if not already done
        for c in chunks:
            raw_id = c.metadata.get("chunk_id", "")
            prefix = f"t{tid}_"
            if not raw_id.startswith(prefix):
                c.metadata["chunk_id"] = f"{prefix}{raw_id}"

            c.metadata["tenant_id"] = tid
            c.metadata["user_id"] = user_id if user_id is not None else -1
            c.metadata["is_global"] = 1 if is_global else 0

        incoming_ids = [c.metadata["chunk_id"] for c in chunks]
        existing = self._collection.get(ids=incoming_ids, include=[])
        existing_ids = set(existing["ids"])

        new_chunks = [c for c in chunks if c.metadata["chunk_id"] not in existing_ids]

        if not new_chunks:
            logger.info("All %d chunks already indexed for tenant %d — skipping", len(chunks), tid)
            return 0

        texts = [c.page_content for c in new_chunks]
        ids = [c.metadata["chunk_id"] for c in new_chunks]
        metadatas = [c.metadata for c in new_chunks]

        logger.info("Generating embeddings for %d chunks (tenant %d)...", len(new_chunks), tid)
        if self._mistral_client:
            response = self._mistral_client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=texts,
            )
            embeddings_list = [item.embedding for item in response.data]
        elif self._local_embedder:
            embeddings_list = self._local_embedder.encode(texts).tolist()
        else:
            embeddings_list = self._embeddings.embed_documents(texts)

        self._collection.add(
            ids=ids,
            embeddings=embeddings_list,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(
            "Added %d chunks to ChromaDB for tenant %d (collection total: %d)",
            len(new_chunks),
            tid,
            self._collection.count(),
        )

        # Rebuild BM25 specifically for this tenant
        self._build_bm25_for_tenant(tid)
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
        tenant_id: Optional[int] = None,
    ) -> List[Document]:
        """
        Cosine similarity search with mandatory tenant isolation.
        """
        if not query.strip():
            logger.warning("search() called with empty query")
            return []

        k = k or RETRIEVAL_TOP_K

        if self._mistral_client:
            response = self._mistral_client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=[query],
            )
            query_embedding = response.data[0].embedding
        elif self._local_embedder:
            query_embedding = self._local_embedder.encode(query).tolist()
        else:
            query_embedding = self._embeddings.embed_query(query)

        # ── Mandatory Tenant-Isolated Filter ────────────────────────
        where_conditions = []
        if tenant_id is not None:
            where_conditions.append({"tenant_id": tenant_id})

        if user_id is not None:
            where_conditions.append({"$or": [{"user_id": user_id}, {"is_global": 1}]})

        if source_filter:
            where_conditions.append({"source": source_filter})

        if len(where_conditions) == 1:
            where = where_conditions[0]
        elif len(where_conditions) > 1:
            where = {"$and": where_conditions}
        else:
            where = None

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, self._collection.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        documents = []
        if results and results.get("documents") and len(results["documents"]) > 0:
            texts_ = results["documents"][0]
            metas = results["metadatas"][0]
            distances = results["distances"][0]

            for text, meta, distance in zip(texts_, metas, distances):
                similarity = round(1 - distance / 2, 4)
                meta["similarity_score"] = similarity
                documents.append(Document(page_content=text, metadata=meta))

        return documents

    def search_bm25(
        self,
        query: str,
        k: Optional[int] = None,
        source_filter: Optional[str] = None,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> List[Document]:
        """
        BM25 search executed strictly on the tenant's dedicated index.
        """
        tid = tenant_id if tenant_id is not None else 1
        bm25_entry = self._bm25_indices.get(tid)
        if not bm25_entry or not query.strip():
            return []

        bm25, docs = bm25_entry
        k = k or RETRIEVAL_TOP_K
        tokenized_query = re.sub(r'[^\w\s]', '', query.lower()).split()
        scores = bm25.get_scores(tokenized_query)

        scored_docs = []
        for score, doc in zip(scores, docs):
            if score > 0:
                is_global = doc.metadata.get("is_global") == 1
                if user_id is not None and doc.metadata.get("user_id") != user_id and not is_global:
                    continue
                if source_filter and doc.metadata.get("source") != source_filter:
                    continue
                scored_doc = Document(page_content=doc.page_content, metadata=doc.metadata.copy())
                scored_doc.metadata["bm25_score"] = float(score)
                scored_docs.append(scored_doc)

        scored_docs.sort(key=lambda d: d.metadata["bm25_score"], reverse=True)
        return scored_docs[:k]

    # ──────────────────────────────────────────────────────────────────
    # MANAGEMENT
    # ──────────────────────────────────────────────────────────────────

    def list_sources(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> List[str]:
        """Return unique filenames visible to user within their tenant."""
        if self._collection.count() == 0:
            return []

        all_items = self._collection.get(include=["metadatas"])
        sources = set()
        for meta in all_items.get("metadatas", []):
            if not meta:
                continue
            if tenant_id is not None and meta.get("tenant_id") != tenant_id:
                continue
            source = meta.get("source", "unknown")
            is_glob = meta.get("is_global") in [1, True, "1", "true"]
            owner_id = meta.get("user_id")
            if is_glob or user_id is None or (owner_id == user_id or str(owner_id) == str(user_id)):
                sources.add(source)
        return sorted(sources)

    def list_sources_by_type(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> dict:
        """Return sources grouped by personal vs company corpus for a tenant."""
        if self._collection.count() == 0:
            return {"personal": [], "global": []}

        all_items = self._collection.get(include=["metadatas"])
        personal = set()
        global_docs = set()
        for meta in all_items.get("metadatas", []):
            if not meta:
                continue
            if tenant_id is not None and meta.get("tenant_id") != tenant_id:
                continue
            source = meta.get("source", "unknown")
            is_glob = meta.get("is_global") in [1, True, "1", "true"]
            owner_id = meta.get("user_id")

            if is_glob:
                global_docs.add(source)
            elif user_id is not None and (owner_id == user_id or str(owner_id) == str(user_id)):
                personal.add(source)
            elif user_id is None:
                personal.add(source)

        return {"personal": sorted(personal), "global": sorted(global_docs)}

    def delete_source(
        self,
        source_filename: str,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> int:
        """
        Delete chunks belonging to a source document within a tenant.
        """
        conditions = [{"source": source_filename}]
        if tenant_id is not None:
            conditions.append({"tenant_id": tenant_id})
        if user_id is not None:
            conditions.append({"user_id": user_id})

        where = {"$and": conditions} if len(conditions) > 1 else conditions[0]
        results = self._collection.get(where=where, include=["metadatas"])

        if not results or not results.get("ids"):
            logger.info("No chunks found for deletion: '%s'", source_filename)
            return 0

        count = len(results["ids"])
        self._collection.delete(ids=results["ids"])

        logger.info(
            "Deleted %d chunks for source '%s' (tenant=%s)",
            count,
            source_filename,
            tenant_id,
        )

        # Rebuild tenant BM25 index
        if tenant_id is not None:
            self._build_bm25_for_tenant(tenant_id)
        else:
            self._build_all_bm25()

        return count

    def delete_all_tenant_chunks(self, tenant_id: int) -> int:
        """Purge all vector chunks for a decommissioned tenant."""
        results = self._collection.get(where={"tenant_id": tenant_id}, include=[])
        if not results or not results.get("ids"):
            return 0
        count = len(results["ids"])
        self._collection.delete(ids=results["ids"])
        self._bm25_indices.pop(tenant_id, None)
        logger.info("Purged %d chunks for tenant %d", count, tenant_id)
        return count

    def get_stats(self, user_id: Optional[int] = None, tenant_id: Optional[int] = None) -> dict:
        """Return summary statistics strictly scoped to a tenant."""
        sources = self.list_sources(user_id=user_id, tenant_id=tenant_id)
        where_conditions = []
        if tenant_id is not None:
            where_conditions.append({"tenant_id": tenant_id})
        if user_id is not None:
            where_conditions.append({"$or": [{"user_id": user_id}, {"is_global": 1}]})

        if len(where_conditions) == 1:
            where = where_conditions[0]
        elif len(where_conditions) > 1:
            where = {"$and": where_conditions}
        else:
            where = None

        if where:
            res = self._collection.get(where=where, include=[])
            total_chunks = len(res["ids"]) if res and "ids" in res else 0
        else:
            total_chunks = self._collection.count()

        return {
            "total_chunks": total_chunks,
            "total_sources": len(sources),
            "sources": sources,
        }

    def is_empty(self) -> bool:
        return self._collection.count() == 0