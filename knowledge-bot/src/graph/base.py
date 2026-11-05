"""
base.py — Abstract Base Interface and Data Structures for Graph Storage.

Defines the contract for multi-tenant knowledge graph storage backends
(e.g., NetworkX in-memory with PostgreSQL persistence, Neo4j, FalkorDB).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class GraphNodeData:
    """Represents an entity node in the knowledge graph."""
    id: str                                  # Normalized canonical ID (e.g. "acme_corp")
    name: str                                # Human-readable label (e.g. "Acme Corporation")
    entity_type: str                         # ORGANIZATION, SYSTEM, POLICY, INCIDENT, DEPARTMENT, METRIC, PERSON
    description: Optional[str] = ""
    source_documents: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type,
            "description": self.description,
            "source_documents": list(self.source_documents),
            "properties": self.properties,
        }


@dataclass
class GraphEdgeData:
    """Represents a directed relationship edge between two entities."""
    source: str                              # Source entity_id
    target: str                              # Target entity_id
    relation: str                            # AFFECTS, GOVERNED_BY, RESPONSIBLE_FOR, DEPLOYED_ON, etc.
    weight: float = 1.0
    context_snippet: Optional[str] = ""
    source_document: Optional[str] = ""
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "weight": self.weight,
            "context_snippet": self.context_snippet,
            "source_document": self.source_document,
            "properties": self.properties,
        }


class BaseGraphStore(ABC):
    """Abstract interface for multi-tenant graph storage."""

    @abstractmethod
    def add_node(self, tenant_id: int, node: GraphNodeData) -> None:
        """Add or update an entity node for a tenant."""
        pass

    @abstractmethod
    def add_edge(self, tenant_id: int, edge: GraphEdgeData) -> None:
        """Add a directed relation edge between entities for a tenant."""
        pass

    @abstractmethod
    def bulk_add(
        self,
        tenant_id: int,
        nodes: List[GraphNodeData],
        edges: List[GraphEdgeData]
    ) -> None:
        """Atomically upsert a collection of nodes and edges for a tenant."""
        pass

    @abstractmethod
    def get_node(self, tenant_id: int, entity_id: str) -> Optional[GraphNodeData]:
        """Fetch a specific node by entity ID within a tenant."""
        pass

    @abstractmethod
    def get_neighbors(
        self,
        tenant_id: int,
        entity_id: str,
        depth: int = 1
    ) -> List[Dict[str, Any]]:
        """Return connected neighbors up to depth hops for an entity."""
        pass

    @abstractmethod
    def find_subgraph(
        self,
        tenant_id: int,
        entity_ids: List[str],
        depth: int = 2,
        max_nodes: int = 30
    ) -> Dict[str, Any]:
        """
        Extract an ego-subgraph seeded by entity_ids.
        Returns a dict: {"nodes": [...], "edges": [...]}
        """
        pass

    @abstractmethod
    def get_top_entities(
        self,
        tenant_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Rank entities by degree centrality / PageRank for a tenant."""
        pass

    @abstractmethod
    def get_stats(self, tenant_id: int) -> Dict[str, Any]:
        """Return graph statistics (node_count, edge_count, entity_types, relation_types)."""
        pass

    @abstractmethod
    def delete_document_entities(self, tenant_id: int, document_name: str) -> int:
        """Cascade-delete edges and orphan nodes originating from a source document."""
        pass

    @abstractmethod
    def delete_tenant_graph(self, tenant_id: int) -> int:
        """Purge an entire tenant's graph upon tenant decommissioning."""
        pass

