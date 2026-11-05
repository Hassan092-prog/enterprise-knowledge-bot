"""
fusion.py — Hybrid Vector + Graph Fusion Retriever.

Bridges dense semantic search and structured graph traversals to enable
multi-hop relational reasoning across documents, departments, and policies.
"""

from typing import Dict, Any, List, Optional
from src.graph.extractor import GraphExtractor
from src.graph import get_graph_store
from src.logger import get_logger

logger = get_logger(__name__)


def retrieve_graph_context(
    query: str,
    tenant_id: int,
    depth: int = 2,
    max_nodes: int = 25
) -> Dict[str, Any]:
    """
    Extract query entities, traverse the tenant's knowledge graph,
    and format connected relationships into a structured context block.
    """
    extractor = GraphExtractor()
    query_entities = extractor.extract_query_entities(query)

    if not query_entities:
        from src.graph import normalize_entity_id
        candidate = normalize_entity_id(query)
        if candidate and len(candidate) >= 3:
            query_entities = [candidate]

    if not query_entities:
        return {
            "context_block": "",
            "subgraph": {"nodes": [], "edges": []},
            "graph_citations": [],
            "matched_entities_count": 0,
        }

    graph_store = get_graph_store()
    subgraph = graph_store.find_subgraph(
        tenant_id=tenant_id,
        entity_ids=query_entities,
        depth=depth,
        max_nodes=max_nodes,
    )

    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if not nodes or not edges:
        return {
            "context_block": "",
            "subgraph": subgraph,
            "graph_citations": [],
            "matched_entities_count": len(nodes),
        }

    # Format into human and LLM-friendly context block
    lines = ["\n--- KNOWLEDGE GRAPH (ENTITIES & RELATIONSHIPS) ---"]
    
    # Group edges by source
    edges_by_source: Dict[str, List[Dict[str, Any]]] = {}
    node_name_map = {n["id"]: f"{n['label']} [{n['type']}]" for n in nodes}

    for e in edges:
        src = e["source"]
        edges_by_source.setdefault(src, []).append(e)

    for n in nodes:
        n_id = n["id"]
        n_label = n["label"]
        n_type = n["type"]
        desc = n.get("description", "")
        connected_edges = edges_by_source.get(n_id, [])

        if connected_edges:
            lines.append(f"• Entity: {n_label} [{n_type}]{f' — {desc}' if desc else ''}")
            for edge in connected_edges[:5]:  # limit lines per node to prevent token bloat
                tgt_label = node_name_map.get(edge["target"], edge["target"])
                rel = edge["relation"]
                snippet = edge.get("context", "").strip().replace("\n", " ")
                if snippet:
                    lines.append(f"    └── {rel} ──> {tgt_label} (Context: {snippet[:120]})")
                else:
                    lines.append(f"    └── {rel} ──> {tgt_label}")

    lines.append("--- END KNOWLEDGE GRAPH ---\n")
    context_block = "\n".join(lines)

    # Prepare structured graph citations
    graph_citations = [
        {
            "id": n["id"],
            "name": n["label"],
            "type": n["type"],
            "degree": n["degree"],
            "sources": n.get("sources", []),
        }
        for n in nodes
    ]

    logger.info(
        "Graph RAG fusion matched %d entities and %d relationships for tenant %d",
        len(nodes), len(edges), tenant_id
    )

    return {
        "context_block": context_block,
        "subgraph": subgraph,
        "graph_citations": graph_citations,
        "matched_entities_count": len(nodes),
    }

