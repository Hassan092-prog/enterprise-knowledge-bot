"""
graph.py — Knowledge Graph API Endpoints.

Provides endpoints for inspecting, visualizing, searching, and managing
the multi-tenant knowledge graph and its entity-relationship network.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import User
from api.dependencies import get_current_user
from src.graph import get_graph_store, normalize_entity_id
from src.graph.extractor import GraphExtractor
from src.activity import log_activity
from src.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


@router.get("/stats")
def get_graph_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Return summary statistics of the tenant's knowledge graph."""
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    store = get_graph_store()
    stats = store.get_stats(tenant_id=current_user.tenant_id)
    top_entities = store.get_top_entities(tenant_id=current_user.tenant_id, limit=10)

    return {
        "tenant_id": current_user.tenant_id,
        "node_count": stats.get("node_count", 0),
        "edge_count": stats.get("edge_count", 0),
        "entity_types": stats.get("entity_types", {}),
        "relation_types": stats.get("relation_types", {}),
        "top_entities": top_entities,
    }


@router.get("/subgraph")
def get_subgraph(
    query: Optional[str] = Query(None, description="Search term or natural language query"),
    depth: int = Query(2, ge=1, le=4, description="Graph traversal hop depth"),
    limit: int = Query(35, ge=5, le=100, description="Max nodes to return"),
    current_user: User = Depends(get_current_user)
):
    """
    Return ego-subgraph of entities and relationships for visualization.
    Accepts search query or falls back to top central entities.
    """
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    store = get_graph_store()

    if query and query.strip():
        extractor = GraphExtractor()
        seeds = extractor.extract_query_entities(query.strip())
        if not seeds:
            seeds = [normalize_entity_id(query.strip())]
    else:
        top = store.get_top_entities(tenant_id=current_user.tenant_id, limit=5)
        seeds = [t["id"] for t in top] if top else []

    subgraph = store.find_subgraph(
        tenant_id=current_user.tenant_id,
        entity_ids=seeds,
        depth=depth,
        max_nodes=limit
    )

    return {
        "tenant_id": current_user.tenant_id,
        "seeds": seeds,
        "nodes": subgraph.get("nodes", []),
        "edges": subgraph.get("edges", []),
    }


@router.get("/entity/{entity_id}")
def get_entity_details(
    entity_id: str,
    current_user: User = Depends(get_current_user)
):
    """Return detailed node information, connected relationships, and source documents."""
    if not current_user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    store = get_graph_store()
    node = store.get_node(tenant_id=current_user.tenant_id, entity_id=entity_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found in tenant graph")

    subgraph = store.find_subgraph(
        tenant_id=current_user.tenant_id,
        entity_ids=[node.id],
        depth=1,
        max_nodes=20
    )

    return {
        "entity": node.to_dict(),
        "connected_nodes": [n for n in subgraph.get("nodes", []) if n["id"] != node.id],
        "relationships": subgraph.get("edges", []),
    }


@router.post("/rebuild")
def rebuild_tenant_graph(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Rebuild tenant's knowledge graph from all existing indexed documents.
    Restricted to Admin / SuperAdmin.
    """
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Forbidden: Admin privilege required to rebuild graph")

    store = get_graph_store()
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    # Purge existing graph
    store.delete_tenant_graph(tenant_id)

    # Fetch all document chunks from ChromaDB for this tenant
    from api.main import get_retriever
    r = get_retriever()
    extractor = GraphExtractor()

    res = r._store._collection.get(where={"tenant_id": tenant_id}, include=["documents", "metadatas"])
    docs = res.get("documents", [])
    metas = res.get("metadatas", [])

    # Group chunk texts by source document
    doc_texts: Dict[str, List[str]] = {}
    for text, meta in zip(docs, metas):
        if not meta or not text:
            continue
        # Skip executive summaries to prevent duplicate entity extraction
        if meta.get("is_summary"):
            continue
        src = meta.get("source", "unknown")
        doc_texts.setdefault(src, []).append(text)

    total_nodes_added = 0
    total_edges_added = 0

    for src_doc, text_chunks in doc_texts.items():
        full_text = "\n\n".join(text_chunks)
        nodes, edges = extractor.extract_from_text(full_text, source_document=src_doc)
        if nodes or edges:
            store.bulk_add(tenant_id=tenant_id, nodes=nodes, edges=edges)
            total_nodes_added += len(nodes)
            total_edges_added += len(edges)

    stats = store.get_stats(tenant_id)

    log_activity(
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="GRAPH_REBUILD",
        category="KNOWLEDGE",
        description=f"Rebuilt knowledge graph ({stats.get('node_count', 0)} nodes, {stats.get('edge_count', 0)} edges)",
        details={"rebuilt_sources": len(doc_texts), "stats": stats}
    )

    return {
        "status": "success",
        "message": f"Successfully rebuilt knowledge graph from {len(doc_texts)} documents",
        "stats": stats,
    }


@router.delete("/clear")
def clear_tenant_graph(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Purge all knowledge graph nodes and edges for the tenant. Admin only."""
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Forbidden: Admin privilege required to clear graph")

    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    store = get_graph_store()
    deleted_count = store.delete_tenant_graph(tenant_id)

    log_activity(
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="GRAPH_CLEARED",
        category="KNOWLEDGE",
        description="Cleared entire knowledge graph for tenant",
        details={"deleted_records": deleted_count}
    )

    return {"status": "success", "message": f"Cleared {deleted_count} graph records"}

