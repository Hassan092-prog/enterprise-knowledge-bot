"""
src.graph — Enterprise Knowledge Graph & Graph RAG Package.
"""

from src.graph.base import BaseGraphStore, GraphNodeData, GraphEdgeData
from src.graph.networkx_store import NetworkXGraphStore, normalize_entity_id
from src.config import GRAPH_BACKEND

_store_instance: BaseGraphStore = None


def get_graph_store() -> BaseGraphStore:
    """Return singleton graph store instance based on GRAPH_BACKEND configuration."""
    global _store_instance
    if _store_instance is None:
        if GRAPH_BACKEND == "neo4j":
            try:
                from src.graph.neo4j_store import Neo4jGraphStore
                _store_instance = Neo4jGraphStore()
            except Exception as e:
                import logging
                logging.getLogger("src.graph").warning(f"Neo4j backend initialization failed ({e}). Falling back to NetworkX.")
                _store_instance = NetworkXGraphStore()
        else:
            _store_instance = NetworkXGraphStore()
    return _store_instance


__all__ = [
    "BaseGraphStore",
    "GraphNodeData",
    "GraphEdgeData",
    "NetworkXGraphStore",
    "normalize_entity_id",
    "get_graph_store",
]

