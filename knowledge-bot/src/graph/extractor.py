"""
extractor.py — Entity and Relationship Extraction Engine for Graph RAG.

Extracts structured domain entities (Organizations, Policies, Systems, Incidents,
Departments, Metrics, People) and directional relations from document text.
Supports fast deterministic pattern-based extraction with optional LLM augmentation.
"""

import re
import json
from typing import List, Dict, Any, Tuple, Optional, Set
from src.graph.base import GraphNodeData, GraphEdgeData
from src.graph.networkx_store import normalize_entity_id
from src.logger import get_logger
from src.config import GRAPH_EXTRACTION_MODE

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN DICTIONARIES & PATTERNS
# ─────────────────────────────────────────────────────────────────────────────

# Known enterprise systems & infrastructure
KNOWN_SYSTEMS = [
    "Payment Gateway", "Core Banking API", "Kubernetes", "PostgreSQL",
    "ChromaDB", "Redis", "MinIO", "Celery Worker", "API Gateway",
    "Active Directory", "Identity Provider", "Cloudflare CDN", "AWS us-east-1",
    "Load Balancer", "Elasticsearch", "Apache Kafka", "Docker Engine"
]

# Known policies & compliance standards
KNOWN_POLICIES = [
    "SOC 2 Type II", "SOC 2", "ISO 27001", "GDPR", "HIPAA", "PCI-DSS",
    "Enterprise Information Security Policy", "Access Control Policy",
    "Password Policy", "Incident Response Policy", "Data Retention Policy",
    "Disaster Recovery Plan", "Business Continuity Plan"
]

# Known corporate departments
KNOWN_DEPARTMENTS = [
    "DevOps & Platform Security", "Platform Engineering", "Security Operations",
    "DevOps", "Human Resources", "Finance", "Legal & Compliance",
    "Executive Leadership", "Research & Development", "Customer Support",
    "Product Management", "IT Operations"
]

# Known organizations
KNOWN_ORGS = [
    "Acme Corporation", "Acme Corp", "Alpha Labs", "Google Workspace",
    "Microsoft Entra ID", "Stripe", "Cloudflare", "Amazon Web Services"
]


class GraphExtractor:
    """Extracts entities and relationships from documents and queries."""

    def __init__(self, mode: str = GRAPH_EXTRACTION_MODE) -> None:
        self.mode = mode.lower()

    def extract_from_text(
        self,
        text: str,
        source_document: str = ""
    ) -> Tuple[List[GraphNodeData], List[GraphEdgeData]]:
        """
        Extract nodes and edges from text content.
        Uses rule-based extraction by default, supplemented by LLM when enabled.
        """
        if not text or len(text.strip()) < 10:
            return [], []

        rule_nodes, rule_edges = self._extract_rule_based(text, source_document)

        if self.mode in ("llm", "hybrid"):
            try:
                llm_nodes, llm_edges = self._extract_llm_based(text, source_document)
                # Merge: LLM edges + Rule edges
                return self._merge_extractions(rule_nodes, rule_edges, llm_nodes, llm_edges)
            except Exception as e:
                logger.warning(f"LLM entity extraction skipped/failed: {e}. Falling back to rule-based.")
                return rule_nodes, rule_edges

        return rule_nodes, rule_edges

    def _extract_rule_based(
        self,
        text: str,
        source_document: str
    ) -> Tuple[List[GraphNodeData], List[GraphEdgeData]]:
        """Fast, deterministic regex & vocabulary entity and relationship extractor."""
        nodes_dict: Dict[str, GraphNodeData] = {}
        edges: List[GraphEdgeData] = []

        def add_entity(name: str, entity_type: str, desc: str = ""):
            canon = normalize_entity_id(name)
            if not canon or len(canon) < 2:
                return None
            if canon not in nodes_dict:
                nodes_dict[canon] = GraphNodeData(
                    id=canon,
                    name=name.strip(),
                    entity_type=entity_type,
                    description=desc,
                    source_documents=[source_document] if source_document else [],
                )
            else:
                if source_document and source_document not in nodes_dict[canon].source_documents:
                    nodes_dict[canon].source_documents.append(source_document)
                if desc and len(desc) > len(nodes_dict[canon].description or ""):
                    nodes_dict[canon].description = desc
            return canon

        # 1. Match Incidents: "Incident Report 104", "INC-2026-01", "Incident #12"
        incident_matches = re.finditer(r'\b(Incident(?:\s+Report)?\s+#?\d+|INC-\d+|SEV-[1-4])\b', text, re.IGNORECASE)
        found_incidents = []
        for m in incident_matches:
            inc_name = m.group(1).strip()
            # Extract sentence snippet as description
            snippet = self._extract_surrounding_sentence(text, m.start())
            canon = add_entity(inc_name, "INCIDENT", snippet)
            if canon:
                found_incidents.append((canon, inc_name, snippet))

        # 2. Match Systems & Infrastructure
        found_systems = []
        for sys in KNOWN_SYSTEMS:
            if re.search(rf'\b{re.escape(sys)}\b', text, re.IGNORECASE):
                canon = add_entity(sys, "SYSTEM", f"Enterprise system: {sys}")
                if canon:
                    found_systems.append(canon)

        # 3. Match Policies & Compliance
        found_policies = []
        for pol in KNOWN_POLICIES:
            if re.search(rf'\b{re.escape(pol)}\b', text, re.IGNORECASE):
                canon = add_entity(pol, "POLICY", f"Enterprise policy or standard: {pol}")
                if canon:
                    found_policies.append(canon)

        # 4. Match Departments
        found_depts = []
        for dept in KNOWN_DEPARTMENTS:
            if re.search(rf'\b{re.escape(dept)}\b', text, re.IGNORECASE):
                canon = add_entity(dept, "DEPARTMENT", f"Organizational division: {dept}")
                if canon:
                    found_depts.append(canon)

        # 5. Match Organizations
        found_orgs = []
        for org in KNOWN_ORGS:
            if re.search(rf'\b{re.escape(org)}\b', text, re.IGNORECASE):
                canon = add_entity(org, "ORGANIZATION", f"Corporate entity: {org}")
                if canon:
                    found_orgs.append(canon)

        # 6. Match Financial Metrics: "revenue", "gross margin", "$48,500,000", "YoY growth"
        metric_matches = re.finditer(r'(\$\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:USD|million)?|\b\d{1,2}\.\d+%\s*(?:YoY|margin|growth)?)', text, re.IGNORECASE)
        found_metrics = []
        for m in metric_matches:
            val = m.group(1).strip()
            if len(val) >= 4:
                metric_name = f"Metric {val}"
                snippet = self._extract_surrounding_sentence(text, m.start())
                canon = add_entity(metric_name, "METRIC", snippet)
                if canon:
                    found_metrics.append((canon, snippet))

        # ── Infer Relationships ──────────────────────────────────────
        # A. Incidents affect Systems
        for inc_id, inc_name, snip in found_incidents:
            for sys_id in found_systems:
                edges.append(GraphEdgeData(
                    source=inc_id,
                    target=sys_id,
                    relation="AFFECTS",
                    weight=1.5,
                    context_snippet=snip[:200],
                    source_document=source_document,
                ))

            # Incidents resolved by or reported to Departments
            for dept_id in found_depts:
                edges.append(GraphEdgeData(
                    source=dept_id,
                    target=inc_id,
                    relation="RESOLVED",
                    weight=1.2,
                    context_snippet=snip[:200],
                    source_document=source_document,
                ))

        # B. Policies govern Systems and Departments
        for pol_id in found_policies:
            for sys_id in found_systems:
                edges.append(GraphEdgeData(
                    source=pol_id,
                    target=sys_id,
                    relation="GOVERNS",
                    weight=1.0,
                    context_snippet="Policy compliance and governance boundary",
                    source_document=source_document,
                ))
            for dept_id in found_depts:
                edges.append(GraphEdgeData(
                    source=pol_id,
                    target=dept_id,
                    relation="MANDATES",
                    weight=1.0,
                    context_snippet="Departmental compliance mandate",
                    source_document=source_document,
                ))

        # C. Organizations report Metrics and own Systems
        for org_id in found_orgs:
            for m_id, snip in found_metrics:
                edges.append(GraphEdgeData(
                    source=org_id,
                    target=m_id,
                    relation="REPORTED",
                    weight=1.0,
                    context_snippet=snip[:200],
                    source_document=source_document,
                ))
            for sys_id in found_systems:
                edges.append(GraphEdgeData(
                    source=org_id,
                    target=sys_id,
                    relation="OPERATES",
                    weight=1.0,
                    context_snippet="Enterprise system operations",
                    source_document=source_document,
                ))

        # Limit maximum inferred edges per document to prevent quadratic blowup
        return list(nodes_dict.values()), edges[:100]

    def _extract_llm_based(
        self,
        text: str,
        source_document: str
    ) -> Tuple[List[GraphNodeData], List[GraphEdgeData]]:
        """LLM-based structured relationship extraction."""
        from src.llm_factory import get_llm
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        # Restrict chunk length for fast parsing
        excerpt = text[:2500]

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a knowledge graph information extractor.
Extract the key entities and relations from the text into strict JSON format with two keys:
1. "entities": list of {{"name": str, "type": "ORGANIZATION"|"SYSTEM"|"POLICY"|"INCIDENT"|"DEPARTMENT"|"METRIC"|"PERSON", "description": str}}
2. "relations": list of {{"source": str, "target": str, "relation": str, "snippet": str}}

Output ONLY valid JSON. No markdown ticks, no preamble."""),
            ("human", "Document: {doc_name}\n\nText:\n{text}")
        ])

        llm = get_llm(streaming=False)
        chain = prompt | llm | StrOutputParser()
        raw = chain.invoke({"doc_name": source_document, "text": excerpt})

        # Clean JSON
        clean_json = raw.strip()
        if clean_json.startswith("```"):
            clean_json = re.sub(r"^```(?:json)?", "", clean_json)
            clean_json = re.sub(r"```$", "", clean_json).strip()

        data = json.loads(clean_json)
        nodes: List[GraphNodeData] = []
        for e in data.get("entities", []):
            name = e.get("name", "").strip()
            if name:
                nodes.append(GraphNodeData(
                    id=normalize_entity_id(name),
                    name=name,
                    entity_type=e.get("type", "ENTITY").upper(),
                    description=e.get("description", ""),
                    source_documents=[source_document] if source_document else [],
                ))

        edges: List[GraphEdgeData] = []
        for r in data.get("relations", []):
            src = r.get("source", "").strip()
            tgt = r.get("target", "").strip()
            rel = r.get("relation", "RELATED_TO").upper().strip()
            if src and tgt:
                edges.append(GraphEdgeData(
                    source=normalize_entity_id(src),
                    target=normalize_entity_id(tgt),
                    relation=rel,
                    context_snippet=r.get("snippet", ""),
                    source_document=source_document,
                ))

        return nodes, edges

    def _merge_extractions(
        self,
        nodes1: List[GraphNodeData],
        edges1: List[GraphEdgeData],
        nodes2: List[GraphNodeData],
        edges2: List[GraphEdgeData]
    ) -> Tuple[List[GraphNodeData], List[GraphEdgeData]]:
        """Combine rule-based and LLM-extracted nodes and edges."""
        merged_nodes: Dict[str, GraphNodeData] = {n.id: n for n in nodes1}
        for n in nodes2:
            if n.id in merged_nodes:
                merged_nodes[n.id].source_documents = list(
                    set(merged_nodes[n.id].source_documents) | set(n.source_documents)
                )
                if n.description and len(n.description) > len(merged_nodes[n.id].description or ""):
                    merged_nodes[n.id].description = n.description
            else:
                merged_nodes[n.id] = n

        # Merge edges deduplicating on (source, target, relation)
        seen_edges: Set[Tuple[str, str, str]] = set()
        merged_edges: List[GraphEdgeData] = []

        for e in edges1 + edges2:
            key = (normalize_entity_id(e.source), normalize_entity_id(e.target), e.relation.upper())
            if key not in seen_edges and key[0] != key[1]:
                seen_edges.add(key)
                merged_edges.append(e)

        return list(merged_nodes.values()), merged_edges

    def _extract_surrounding_sentence(self, text: str, pos: int) -> str:
        """Find the sentence containing the match position."""
        start = max(0, text.rfind(".", 0, pos) + 1)
        end = text.find(".", pos)
        if end == -1:
            end = len(text)
        sentence = text[start:end].strip()
        return sentence[:200]

    def extract_query_entities(self, query: str) -> List[str]:
        """
        Extract named entity phrases, incident numbers, and key concepts
        from a user's natural language question.
        """
        if not query:
            return []

        candidates: List[str] = []

        # 1. Match incident identifiers: "incident 104", "inc-104", "report 104"
        inc_matches = re.findall(r'(?:incident|report|inc)\s*#?\s*(\d+|[a-zA-Z0-9_-]+)', query, re.IGNORECASE)
        for num in inc_matches:
            candidates.append(f"incident_report_{num}")
            candidates.append(f"incident_{num}")

        # 2. Match known systems, policies, departments, and organizations
        low_q = query.lower()
        for term in KNOWN_SYSTEMS + KNOWN_POLICIES + KNOWN_DEPARTMENTS + KNOWN_ORGS:
            if term.lower() in low_q:
                candidates.append(normalize_entity_id(term))

        # 3. Capitalized multi-word sequences (e.g. "Acme Corporation", "Project Titan")
        cap_phrases = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b', query)
        for phrase in cap_phrases:
            candidates.append(normalize_entity_id(phrase))

        # 4. Standalone significant capitalized words
        cap_singles = re.findall(r'\b[A-Z][a-zA-Z0-9_]{2,}\b', query)
        stopwords = {"What", "Which", "When", "Where", "How", "Tell", "Explain", "List", "Give", "Can", "Show", "Does"}
        for word in cap_singles:
            if word not in stopwords:
                candidates.append(normalize_entity_id(word))

        # Deduplicate preserving order
        return list(dict.fromkeys(candidates))
