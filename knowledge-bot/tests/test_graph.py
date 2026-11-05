"""
test_graph.py — Comprehensive Unit & Integration Tests for Knowledge Graph & Graph RAG.

Tests:
1. Multi-tenant node & edge persistence and isolation.
2. Rule-based entity & relation extraction from enterprise text.
3. Multi-hop ego-subgraph traversal and centrality ranking.
4. Cascade document deletion and orphan node pruning.
5. Hybrid Graph RAG fusion context formatting.
"""

import pytest
from src.graph.base import GraphNodeData, GraphEdgeData
from src.graph.networkx_store import NetworkXGraphStore, normalize_entity_id
from src.graph.extractor import GraphExtractor
from src.graph.fusion import retrieve_graph_context
from src.database import SessionLocal, run_db_migrations
from src.models import KnowledgeNode, KnowledgeEdge, Tenant


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure database schema is migrated and test tenants exist."""
    run_db_migrations()
    test_tenant_ids = [8801, 8802, 8803, 8804, 8805]
    with SessionLocal() as db:
        for tid in test_tenant_ids:
            if not db.query(Tenant).filter(Tenant.id == tid).first():
                db.add(Tenant(id=tid, name=f"Graph Test Org {tid}", slug=f"graph-test-{tid}", join_code=f"GT-{tid}"))
        db.commit()
    yield
    with SessionLocal() as db:
        for tid in test_tenant_ids:
            db.query(KnowledgeEdge).filter(KnowledgeEdge.tenant_id == tid).delete()
            db.query(KnowledgeNode).filter(KnowledgeNode.tenant_id == tid).delete()
            db.query(Tenant).filter(Tenant.id == tid).delete()
        db.commit()


def test_normalize_entity_id():
    """Verify canonical entity ID normalization."""
    assert normalize_entity_id("Acme Corporation") == "acme_corporation"
    assert normalize_entity_id("Incident Report #104") == "incident_report_104"
    assert normalize_entity_id("  Payment Gateway!  ") == "payment_gateway"
    assert normalize_entity_id("SOC 2 Type II") == "soc_2_type_ii"


def test_graph_store_multi_tenant_isolation():
    """Verify strict tenant isolation between graphs."""
    store = NetworkXGraphStore()
    t1 = 8801
    t2 = 8802

    # Clean up any leftover test data
    store.delete_tenant_graph(t1)
    store.delete_tenant_graph(t2)

    # Add node to Tenant 1
    node1 = GraphNodeData(
        id="payment_gateway",
        name="Payment Gateway",
        entity_type="SYSTEM",
        description="Core processing engine",
        source_documents=["sec_policy.txt"]
    )
    store.add_node(t1, node1)

    # Add node to Tenant 2
    node2 = GraphNodeData(
        id="acme_robotics",
        name="Acme Robotics",
        entity_type="ORGANIZATION",
        description="Robotics division",
        source_documents=["annual_review.txt"]
    )
    store.add_node(t2, node2)

    # Tenant 1 should only see its node
    assert store.get_node(t1, "payment_gateway") is not None
    assert store.get_node(t1, "acme_robotics") is None

    # Tenant 2 should only see its node
    assert store.get_node(t2, "acme_robotics") is not None
    assert store.get_node(t2, "payment_gateway") is None

    # Clean up
    store.delete_tenant_graph(t1)
    store.delete_tenant_graph(t2)


def test_graph_multi_hop_traversal():
    """Verify 2-hop graph traversal and subgraph extraction."""
    store = NetworkXGraphStore()
    t_id = 8803
    store.delete_tenant_graph(t_id)

    # Build A -> B -> C network
    # Incident 104 -> AFFECTS -> Payment Gateway -> GOVERNED_BY -> Security Policy
    nodes = [
        GraphNodeData(id="inc_104", name="Incident 104", entity_type="INCIDENT", source_documents=["inc104.txt"]),
        GraphNodeData(id="payment_gw", name="Payment Gateway", entity_type="SYSTEM", source_documents=["inc104.txt"]),
        GraphNodeData(id="sec_policy", name="Security Policy", entity_type="POLICY", source_documents=["sec_policy.txt"]),
    ]
    edges = [
        GraphEdgeData(source="inc_104", target="payment_gw", relation="AFFECTS", source_document="inc104.txt"),
        GraphEdgeData(source="sec_policy", target="payment_gw", relation="GOVERNS", source_document="sec_policy.txt"),
    ]
    store.bulk_add(t_id, nodes, edges)

    # 1-hop from inc_104 should reach payment_gw
    sub1 = store.find_subgraph(t_id, ["inc_104"], depth=1)
    node_ids_1 = {n["id"] for n in sub1["nodes"]}
    assert "inc_104" in node_ids_1
    assert "payment_gw" in node_ids_1
    assert "sec_policy" not in node_ids_1

    # 2-hop from inc_104 should reach sec_policy through payment_gw
    sub2 = store.find_subgraph(t_id, ["inc_104"], depth=2)
    node_ids_2 = {n["id"] for n in sub2["nodes"]}
    assert "inc_104" in node_ids_2
    assert "payment_gw" in node_ids_2
    assert "sec_policy" in node_ids_2
    assert len(sub2["edges"]) >= 2

    # Verify stats
    stats = store.get_stats(t_id)
    assert stats["node_count"] == 3
    assert stats["edge_count"] == 2
    assert "INCIDENT" in stats["entity_types"]

    store.delete_tenant_graph(t_id)


def test_entity_extractor_rules():
    """Verify rule-based extraction from unstructured enterprise document text."""
    extractor = GraphExtractor(mode="rule")
    sample_text = (
        "During Incident Report 104, the Payment Gateway service in AWS us-east-1 experienced downtime. "
        "The DevOps & Platform Security team resolved the outage according to the Enterprise Information Security Policy. "
        "Acme Corporation reported consolidated revenue of $48,500,000 USD with 18.2% YoY growth."
    )

    nodes, edges = extractor.extract_from_text(sample_text, source_document="incident_104.txt")

    node_types = {n.entity_type for n in nodes}
    node_names = {n.name for n in nodes}

    assert "INCIDENT" in node_types
    assert "SYSTEM" in node_types
    assert "DEPARTMENT" in node_types
    assert "POLICY" in node_types
    assert "ORGANIZATION" in node_types

    assert any("Incident" in n for n in node_names)
    assert "Payment Gateway" in node_names
    assert "Enterprise Information Security Policy" in node_names

    # Verify extracted relationships
    edge_relations = {e.relation for e in edges}
    assert "AFFECTS" in edge_relations or "GOVERNS" in edge_relations or "RESOLVED" in edge_relations

    # Test query entity extraction
    q = "Which systems were affected during Incident Report 104?"
    query_entities = extractor.extract_query_entities(q)
    assert any("incident" in qe for qe in query_entities)


def test_cascade_document_deletion():
    """Verify deleting a document prunes only its edges and orphan nodes."""
    store = NetworkXGraphStore()
    t_id = 8804
    store.delete_tenant_graph(t_id)

    # Document 1 adds: A -> B
    # Document 2 adds: B -> C
    nodes1 = [
        GraphNodeData(id="node_a", name="Node A", entity_type="SYSTEM", source_documents=["doc1.txt"]),
        GraphNodeData(id="node_b", name="Node B", entity_type="SYSTEM", source_documents=["doc1.txt", "doc2.txt"]),
    ]
    edges1 = [
        GraphEdgeData(source="node_a", target="node_b", relation="CONNECTS", source_document="doc1.txt"),
    ]
    store.bulk_add(t_id, nodes1, edges1)

    nodes2 = [
        GraphNodeData(id="node_b", name="Node B", entity_type="SYSTEM", source_documents=["doc1.txt", "doc2.txt"]),
        GraphNodeData(id="node_c", name="Node C", entity_type="SYSTEM", source_documents=["doc2.txt"]),
    ]
    edges2 = [
        GraphEdgeData(source="node_b", target="node_c", relation="SENDS_TO", source_document="doc2.txt"),
    ]
    store.bulk_add(t_id, nodes2, edges2)

    assert store.get_stats(t_id)["node_count"] == 3
    assert store.get_stats(t_id)["edge_count"] == 2

    # Delete doc1.txt -> node_a should be pruned (orphan), node_b should remain (referenced by doc2.txt)
    store.delete_document_entities(t_id, "doc1.txt")

    stats = store.get_stats(t_id)
    assert stats["edge_count"] == 1
    assert store.get_node(t_id, "node_a") is None
    assert store.get_node(t_id, "node_b") is not None
    assert store.get_node(t_id, "node_c") is not None

    store.delete_tenant_graph(t_id)


def test_graph_fusion_context():
    """Verify hybrid fusion context block generation."""
    store = NetworkXGraphStore()
    t_id = 8805
    store.delete_tenant_graph(t_id)

    nodes = [
        GraphNodeData(id="incident_report_104", name="Incident Report 104", entity_type="INCIDENT", description="Payment outage"),
        GraphNodeData(id="payment_gateway", name="Payment Gateway", entity_type="SYSTEM", description="Card transactions"),
    ]
    edges = [
        GraphEdgeData(
            source="incident_report_104",
            target="payment_gateway",
            relation="AFFECTS",
            context_snippet="Service degradation in payment pipeline"
        )
    ]
    store.bulk_add(t_id, nodes, edges)

    fusion_res = retrieve_graph_context("Tell me about Incident Report 104", tenant_id=t_id)
    assert "KNOWLEDGE GRAPH" in fusion_res["context_block"]
    assert "Incident Report 104" in fusion_res["context_block"]
    assert "Payment Gateway" in fusion_res["context_block"]
    assert "AFFECTS" in fusion_res["context_block"]
    assert len(fusion_res["graph_citations"]) >= 1

    store.delete_tenant_graph(t_id)
