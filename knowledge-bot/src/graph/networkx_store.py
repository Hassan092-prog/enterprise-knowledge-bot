"""
networkx_store.py — Multi-Tenant NetworkX In-Memory Knowledge Graph with PostgreSQL Persistence.

Combines microsecond graph traversal (BFS, ego-graphs, PageRank) in memory with
ACID durability, cascade deletion, and multi-tenant isolation in PostgreSQL.
"""

import json
import logging
from typing import List, Dict, Any, Optional, Set
import networkx as nx

from src.graph.base import BaseGraphStore, GraphNodeData, GraphEdgeData
from src.database import SessionLocal
from src.models import KnowledgeNode, KnowledgeEdge
from src.logger import get_logger

logger = get_logger(__name__)


def normalize_entity_id(text: str) -> str:
    """Canonicalize entity string to snake_case identifier."""
    if not text:
        return ""
    clean = text.strip().lower()
    # Replace non-alphanumeric chars with underscore
    normalized = "".join(c if c.isalnum() else "_" for c in clean)
    # Collapse consecutive underscores
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


class NetworkXGraphStore(BaseGraphStore):
    """
    Multi-tenant knowledge graph engine powered by NetworkX MultiDiGraph
    and backed by PostgreSQL `knowledge_nodes` and `knowledge_edges`.
    """

    def __init__(self) -> None:
        self._graphs: Dict[int, nx.MultiDiGraph] = {}

    def _ensure_tenant_graph(self, tenant_id: int) -> nx.MultiDiGraph:
        """Load tenant graph from PostgreSQL if not already in memory."""
        if tenant_id in self._graphs:
            return self._graphs[tenant_id]

        g = nx.MultiDiGraph()
        with SessionLocal() as db:
            # 1. Load nodes
            nodes = db.query(KnowledgeNode).filter(KnowledgeNode.tenant_id == tenant_id).all()
            for n in nodes:
                try:
                    src_docs = set(json.loads(n.source_documents)) if n.source_documents else set()
                except Exception:
                    src_docs = set()

                try:
                    props = json.loads(n.properties_json) if n.properties_json else {}
                except Exception:
                    props = {}

                g.add_node(
                    n.entity_id,
                    id=n.entity_id,
                    name=n.name,
                    entity_type=n.entity_type,
                    description=n.description or "",
                    source_documents=src_docs,
                    properties=props,
                )

            # 2. Load edges
            edges = db.query(KnowledgeEdge).filter(KnowledgeEdge.tenant_id == tenant_id).all()
            for e in edges:
                try:
                    props = json.loads(e.properties_json) if e.properties_json else {}
                except Exception:
                    props = {}

                g.add_edge(
                    e.source_entity_id,
                    e.target_entity_id,
                    key=e.relation_type,
                    relation=e.relation_type,
                    weight=float(e.weight or 1.0),
                    context_snippet=e.context_snippet or "",
                    source_document=e.source_document or "",
                    properties=props,
                )

        self._graphs[tenant_id] = g
        logger.info("Loaded graph for tenant %d: %d nodes, %d edges", tenant_id, g.number_of_nodes(), g.number_of_edges())
        return g

    def add_node(self, tenant_id: int, node: GraphNodeData) -> None:
        """Upsert a single node in memory and PostgreSQL."""
        self.bulk_add(tenant_id, [node], [])

    def add_edge(self, tenant_id: int, edge: GraphEdgeData) -> None:
        """Upsert a single edge in memory and PostgreSQL."""
        self.bulk_add(tenant_id, [], [edge])

    def bulk_add(
        self,
        tenant_id: int,
        nodes: List[GraphNodeData],
        edges: List[GraphEdgeData]
    ) -> None:
        """Atomically upsert nodes and edges into memory and PostgreSQL."""
        g = self._ensure_tenant_graph(tenant_id)

        with SessionLocal() as db:
            # Upsert nodes
            for n in nodes:
                entity_id = normalize_entity_id(n.id or n.name)
                if not entity_id:
                    continue

                existing_db_node = db.query(KnowledgeNode).filter(
                    KnowledgeNode.tenant_id == tenant_id,
                    KnowledgeNode.entity_id == entity_id
                ).first()

                new_docs = set(n.source_documents)
                props = n.properties or {}

                if existing_db_node:
                    try:
                        cur_docs = set(json.loads(existing_db_node.source_documents)) if existing_db_node.source_documents else set()
                    except Exception:
                        cur_docs = set()
                    merged_docs = cur_docs | new_docs
                    existing_db_node.source_documents = json.dumps(sorted(merged_docs))
                    if n.description and len(n.description) > len(existing_db_node.description or ""):
                        existing_db_node.description = n.description
                    if n.entity_type and n.entity_type != "UNKNOWN":
                        existing_db_node.entity_type = n.entity_type
                else:
                    new_db_node = KnowledgeNode(
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        name=n.name,
                        entity_type=n.entity_type or "ENTITY",
                        description=n.description or "",
                        source_documents=json.dumps(sorted(new_docs)),
                        properties_json=json.dumps(props) if props else None,
                    )
                    db.add(new_db_node)

                # Update in-memory graph
                if g.has_node(entity_id):
                    g.nodes[entity_id]["source_documents"].update(new_docs)
                    if n.description and len(n.description) > len(g.nodes[entity_id].get("description", "")):
                        g.nodes[entity_id]["description"] = n.description
                    if n.entity_type and n.entity_type != "UNKNOWN":
                        g.nodes[entity_id]["entity_type"] = n.entity_type
                else:
                    g.add_node(
                        entity_id,
                        id=entity_id,
                        name=n.name,
                        entity_type=n.entity_type or "ENTITY",
                        description=n.description or "",
                        source_documents=new_docs,
                        properties=props,
                    )

            # Upsert edges
            for e in edges:
                src_id = normalize_entity_id(e.source)
                tgt_id = normalize_entity_id(e.target)
                rel_type = (e.relation or "RELATED_TO").upper().strip()

                if not src_id or not tgt_id or src_id == tgt_id:
                    continue

                # Ensure endpoints exist as minimal nodes if not already present
                for end_id, orig_name in [(src_id, e.source), (tgt_id, e.target)]:
                    if not g.has_node(end_id):
                        g.add_node(
                            end_id,
                            id=end_id,
                            name=orig_name,
                            entity_type="ENTITY",
                            description="",
                            source_documents={e.source_document} if e.source_document else set(),
                            properties={},
                        )
                        db_endpoint = db.query(KnowledgeNode).filter(
                            KnowledgeNode.tenant_id == tenant_id,
                            KnowledgeNode.entity_id == end_id
                        ).first()
                        if not db_endpoint:
                            db.add(KnowledgeNode(
                                tenant_id=tenant_id,
                                entity_id=end_id,
                                name=orig_name,
                                entity_type="ENTITY",
                                source_documents=json.dumps([e.source_document]) if e.source_document else "[]",
                            ))

                existing_edge = db.query(KnowledgeEdge).filter(
                    KnowledgeEdge.tenant_id == tenant_id,
                    KnowledgeEdge.source_entity_id == src_id,
                    KnowledgeEdge.target_entity_id == tgt_id,
                    KnowledgeEdge.relation_type == rel_type
                ).first()

                if existing_edge:
                    existing_edge.weight = (existing_edge.weight or 1) + 1
                    if e.context_snippet and len(e.context_snippet) > len(existing_edge.context_snippet or ""):
                        existing_edge.context_snippet = e.context_snippet
                    if e.source_document:
                        existing_edge.source_document = e.source_document
                else:
                    new_db_edge = KnowledgeEdge(
                        tenant_id=tenant_id,
                        source_entity_id=src_id,
                        target_entity_id=tgt_id,
                        relation_type=rel_type,
                        weight=1,
                        context_snippet=e.context_snippet or "",
                        source_document=e.source_document or "",
                        properties_json=json.dumps(e.properties) if e.properties else None,
                    )
                    db.add(new_db_edge)

                # Update in-memory graph
                if g.has_edge(src_id, tgt_id, key=rel_type):
                    g[src_id][tgt_id][rel_type]["weight"] += 1.0
                    if e.context_snippet:
                        g[src_id][tgt_id][rel_type]["context_snippet"] = e.context_snippet
                else:
                    g.add_edge(
                        src_id,
                        tgt_id,
                        key=rel_type,
                        relation=rel_type,
                        weight=float(e.weight or 1.0),
                        context_snippet=e.context_snippet or "",
                        source_document=e.source_document or "",
                        properties=e.properties or {},
                    )

            db.commit()

        logger.info(
            "Indexed %d nodes and %d edges into tenant %d knowledge graph (Total: %d nodes, %d edges)",
            len(nodes), len(edges), tenant_id, g.number_of_nodes(), g.number_of_edges()
        )

    def get_node(self, tenant_id: int, entity_id: str) -> Optional[GraphNodeData]:
        """Fetch node by entity ID."""
        g = self._ensure_tenant_graph(tenant_id)
        canon_id = normalize_entity_id(entity_id)
        if not g.has_node(canon_id):
            return None
        data = g.nodes[canon_id]
        return GraphNodeData(
            id=canon_id,
            name=data.get("name", entity_id),
            entity_type=data.get("entity_type", "ENTITY"),
            description=data.get("description", ""),
            source_documents=list(data.get("source_documents", [])),
            properties=data.get("properties", {}),
        )

    def get_neighbors(
        self,
        tenant_id: int,
        entity_id: str,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """Return connected neighbors for an entity."""
        sub = self.find_subgraph(tenant_id, [entity_id], depth=depth)
        canon_id = normalize_entity_id(entity_id)
        return [n for n in sub["nodes"] if n["id"] != canon_id]

    def find_subgraph(
        self,
        tenant_id: int,
        entity_ids: List[str],
        depth: int = 2,
        max_nodes: int = 30
    ) -> Dict[str, Any]:
        """
        Extract multi-hop ego-subgraph seeded by entity_ids.
        Returns D3 / ForceGraph compatible dict: {"nodes": [...], "edges": [...]}
        """
        g = self._ensure_tenant_graph(tenant_id)
        if g.number_of_nodes() == 0:
            return {"nodes": [], "edges": []}

        # Resolve seed nodes in the graph
        matched_seeds: Set[str] = set()
        for raw_id in entity_ids:
            canon = normalize_entity_id(raw_id)
            if g.has_node(canon):
                matched_seeds.add(canon)
            else:
                # Fuzzy fallback: check if raw_id is substring of any node name or id
                low_raw = raw_id.lower().strip()
                if len(low_raw) >= 3:
                    for n, data in g.nodes(data=True):
                        if low_raw in n or low_raw in data.get("name", "").lower():
                            matched_seeds.add(n)
                            if len(matched_seeds) >= 5:
                                break

        if not matched_seeds:
            return {"nodes": [], "edges": []}

        # Multi-hop BFS traversal (bidirectional)
        visited_nodes: Set[str] = set(matched_seeds)
        frontier: Set[str] = set(matched_seeds)

        for _ in range(depth):
            next_frontier: Set[str] = set()
            for current in frontier:
                # Outgoing neighbors
                for succ in g.successors(current):
                    if succ not in visited_nodes:
                        next_frontier.add(succ)
                # Incoming neighbors
                for pred in g.predecessors(current):
                    if pred not in visited_nodes:
                        next_frontier.add(pred)

            visited_nodes.update(next_frontier)
            frontier = next_frontier
            if len(visited_nodes) >= max_nodes:
                break

        # If too many nodes, keep top ones by degree centrality
        if len(visited_nodes) > max_nodes:
            sorted_by_degree = sorted(
                visited_nodes,
                key=lambda n: (1 if n in matched_seeds else 0, g.degree(n)),
                reverse=True
            )
            visited_nodes = set(sorted_by_degree[:max_nodes])

        # Build final subgraph nodes and edges
        nodes_out = []
        for n in visited_nodes:
            data = g.nodes[n]
            nodes_out.append({
                "id": n,
                "label": data.get("name", n),
                "type": data.get("entity_type", "ENTITY"),
                "degree": g.degree(n),
                "description": data.get("description", ""),
                "sources": sorted(list(data.get("source_documents", []))),
                "is_seed": n in matched_seeds,
            })

        edges_out = []
        for u in visited_nodes:
            for v in g.successors(u):
                if v in visited_nodes:
                    for key, edge_data in g[u][v].items():
                        edges_out.append({
                            "source": u,
                            "target": v,
                            "relation": edge_data.get("relation", key),
                            "weight": edge_data.get("weight", 1.0),
                            "context": edge_data.get("context_snippet", ""),
                            "source_document": edge_data.get("source_document", ""),
                        })

        return {
            "nodes": sorted(nodes_out, key=lambda x: (1 if x["is_seed"] else 0, x["degree"]), reverse=True),
            "edges": edges_out,
        }

    def get_top_entities(
        self,
        tenant_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Rank entities by degree centrality."""
        g = self._ensure_tenant_graph(tenant_id)
        if g.number_of_nodes() == 0:
            return []

        sorted_nodes = sorted(g.nodes(data=True), key=lambda x: g.degree(x[0]), reverse=True)
        results = []
        for n, data in sorted_nodes[:limit]:
            results.append({
                "id": n,
                "name": data.get("name", n),
                "type": data.get("entity_type", "ENTITY"),
                "degree": g.degree(n),
                "sources_count": len(data.get("source_documents", [])),
                "description": data.get("description", ""),
            })
        return results

    def get_stats(self, tenant_id: int) -> Dict[str, Any]:
        """Return graph summary metrics."""
        g = self._ensure_tenant_graph(tenant_id)
        entity_types: Dict[str, int] = {}
        for _, data in g.nodes(data=True):
            t = data.get("entity_type", "ENTITY")
            entity_types[t] = entity_types.get(t, 0) + 1

        relation_types: Dict[str, int] = {}
        for _, _, _, data in g.edges(keys=True, data=True):
            r = data.get("relation", "RELATED_TO")
            relation_types[r] = relation_types.get(r, 0) + 1

        return {
            "node_count": g.number_of_nodes(),
            "edge_count": g.number_of_edges(),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def delete_document_entities(self, tenant_id: int, document_name: str) -> int:
        """Cascade-delete edges originating from document and prune orphan nodes."""
        g = self._ensure_tenant_graph(tenant_id)
        deleted_edges_count = 0

        with SessionLocal() as db:
            # 1. Delete edges in DB
            db_edges = db.query(KnowledgeEdge).filter(
                KnowledgeEdge.tenant_id == tenant_id,
                KnowledgeEdge.source_document == document_name
            ).all()
            deleted_edges_count = len(db_edges)
            for e in db_edges:
                db.delete(e)

            # 2. Update nodes in DB
            nodes = db.query(KnowledgeNode).filter(KnowledgeNode.tenant_id == tenant_id).all()
            for n in nodes:
                try:
                    src_docs = set(json.loads(n.source_documents)) if n.source_documents else set()
                except Exception:
                    src_docs = set()
                if document_name in src_docs:
                    src_docs.remove(document_name)
                    n.source_documents = json.dumps(sorted(src_docs))
                    # Prune orphan nodes with no remaining documents
                    if not src_docs:
                        has_edges = db.query(KnowledgeEdge).filter(
                            KnowledgeEdge.tenant_id == tenant_id,
                            (KnowledgeEdge.source_entity_id == n.entity_id) |
                            (KnowledgeEdge.target_entity_id == n.entity_id)
                        ).first()
                        if not has_edges:
                            db.delete(n)

            db.commit()

        # 3. Synchronize in-memory graph
        edges_to_remove = [
            (u, v, k)
            for u, v, k, d in g.edges(keys=True, data=True)
            if d.get("source_document") == document_name
        ]
        for u, v, k in edges_to_remove:
            g.remove_edge(u, v, key=k)

        nodes_to_remove = []
        for n, d in g.nodes(data=True):
            src_docs = d.get("source_documents", set())
            src_docs.discard(document_name)
            if not src_docs and g.degree(n) == 0:
                nodes_to_remove.append(n)

        for n in nodes_to_remove:
            g.remove_node(n)

        logger.info(
            "Purged document '%s' from tenant %d graph (removed %d edges, %d orphan nodes)",
            document_name, tenant_id, deleted_edges_count, len(nodes_to_remove)
        )
        return deleted_edges_count

    def delete_tenant_graph(self, tenant_id: int) -> int:
        """Purge entire graph for a tenant."""
        with SessionLocal() as db:
            e_count = db.query(KnowledgeEdge).filter(KnowledgeEdge.tenant_id == tenant_id).delete()
            n_count = db.query(KnowledgeNode).filter(KnowledgeNode.tenant_id == tenant_id).delete()
            db.commit()

        self._graphs.pop(tenant_id, None)
        logger.info("Purged graph for tenant %d: %d nodes, %d edges deleted", tenant_id, n_count, e_count)
        return e_count + n_count

