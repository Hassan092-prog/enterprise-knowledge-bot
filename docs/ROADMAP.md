# Strategic Engineering Roadmap & Milestones

**Project:** Enterprise Knowledge Bot  
**Version:** 2.0 (PostgreSQL + Standalone ChromaDB + Celery + Next.js 15)  
**Status:** Production-Ready Core, Scaling to Enterprise Cloud

---

## 🧭 Milestone Progress Overview

| Phase | Milestone Name | Focus Area | Status |
|:---:|---|---|:---:|
| **Phase 1** | **Multi-Format Ingestion Engine** | PDF + OCR, DOCX, TXT, CSV parsing | ✅ **Completed** |
| **Phase 2** | **Hybrid Vector Store Architecture** | ChromaDB, BM25, and metadata indexing | ✅ **Completed** |
| **Phase 3** | **Tabular Data Agent & Routing** | In-memory Pandas agent for CSV math | ✅ **Completed** |
| **Phase 4** | **Generation & Precise Citations** | LangChain prompt chains, executive summaries | ✅ **Completed** |
| **Phase 5** | **Relational Migration & Auth** | PostgreSQL 15, JWT authentication, sessions | ✅ **Completed** |
| **Phase 6** | **Next.js 15 Streaming Frontend** | React 19, Markdown SSE streaming, mentions | ✅ **Completed** |
| **Phase 7** | **Advanced Retrieval & Worker Scaling** | Standalone ChromaDB, Celery + Redis, RRF, CrossEncoder, MMR, 3-tier RBAC | ✅ **Completed** |
| **Phase 8** | **Ingestion Transparency & Polling** | Real-time upload status & task polling | ✅ **Completed** |
| **Phase 9** | **Distributed Object Storage (MinIO/S3)** | Decoupled cloud document storage & presigned URLs | ✅ **Completed** |
| **Phase 10** | **Graph RAG & Knowledge Graph Engine** | Multi-tenant NetworkX/PostgreSQL Graph Store & Subgraph Fusion | ✅ **Completed** |
| **Phase 11** | **Observability & Cost Governance** | OpenTelemetry spans, tenant token accounting & budget caps | ✅ **Completed** |
| **Phase 12** | **Enterprise SSO & SAML / OAuth2** | Corporate Identity Providers (Okta / Azure AD / OIDC) | 🟡 **Next Up** |

---

## 🎯 Milestone Specifications & Delivery Summary

### Phase 8: Ingestion Transparency & Task Polling ✅ Completed
**Problem Statement:**  
Previously, `/upload` queued an asynchronous Celery task and immediately returned a `task_id`. However, the frontend immediately displayed a success toast and called `fetchDocuments()`, creating a race condition where the document had not yet been processed by the worker.

**Delivered Capabilities:**
1. **Backend Status Endpoint (`/tasks/{task_id}`):**
   - FastAPI route querying Celery's `AsyncResult` returning status (`PENDING`, `PROGRESS`, `SUCCESS`, `FAILURE`) and stage metadata.
2. **Worker Progress Reporting:**
   - Updated `process_document` in `src/worker.py` to record step-by-step progress states: `Parsing` $\rightarrow$ `Chunking` $\rightarrow$ `Summarizing` $\rightarrow$ `Embedding` $\rightarrow$ `Indexed`.
3. **Frontend Ingestion Stepper:**
   - Real-time polling badge in `frontend/app/page.tsx` displaying live stage progression and auto-refreshing the document list upon completion.

---

### Phase 9: Distributed Object Storage (MinIO / S3) ✅ Completed
**Problem Statement:**  
Document files were originally written to local disk directories (`data/uploads`) mounted via Docker volumes, creating brittle coupling in multi-node cloud environments.

**Delivered Capabilities:**
1. **S3 / MinIO Storage Backend:**
   - Abstracted storage behind a pluggable `StorageProvider` interface (`LocalStorageProvider`, `S3StorageProvider`).
   - Added MinIO container (`knowledge-bot-minio`, ports `9010`/`9011`) with AWS SDK S3 client compatibility.
2. **Multi-Tenant Canonical Storage Paths:**
   - Documents segregated under `tenants/{tenant_id}/users/{user_id}/{filename}` and `tenants/{tenant_id}/global/{filename}`.
3. **Presigned Upload & Download URLs:**
   - Fast, secure file streaming and direct browser downloads via authenticated presigned GET/PUT URLs.
4. **Data Migration Tooling:**
   - Executable migration script (`scripts/migrate_local_to_s3.py`) with dry-run verification and automatic cascade deletion.

---

### Phase 10: Graph RAG & Knowledge Graph Engine ✅ Completed
**Problem Statement:**  
Pure vector similarity struggles with multi-hop relationships across enterprise documents (e.g., cross-departmental incident impacts, compliance policies, and organizational hierarchy).

**Delivered Capabilities:**
1. **Relational Graph Schema:**
   - PostgreSQL persistence with `KnowledgeNode` and `KnowledgeEdge` tables enforcing `tenant_id` foreign key isolation with `ON DELETE CASCADE`.
2. **Multi-Tenant NetworkX Graph Store:**
   - High-performance in-memory `MultiDiGraph` with lazy loading from PostgreSQL, atomic bulk indexing, BFS multi-hop traversals, degree centrality ranking, and orphan node pruning.
3. **Entity & Relation Extraction:**
   - Hybrid rule-based + LLM extraction identifying 7 enterprise entity types (`INCIDENT`, `SYSTEM`, `POLICY`, `DEPARTMENT`, `ORGANIZATION`, `METRIC`, `PERSON`) and directed relations (`AFFECTS`, `GOVERNS`, `RESOLVED`, `MANDATES`, etc.).
4. **Hybrid Vector + Graph Fusion Retriever:**
   - Seed query entity extraction $\rightarrow$ ego-subgraph traversal $\rightarrow$ structured Markdown synthesis and citation metadata (`is_graph: True`).
5. **Admin Knowledge Graph Explorer UI:**
   - Interactive Knowledge Graph visualization tab in `/admin` with live metrics, entity search, hop depth selector, entity node explorer, and link inspector.

---

### Phase 11: Production Observability & Cost Governance ✅ Completed
**Problem Statement:**  
Enterprise production operations require fine-grained visibility into token usage, cost per tenant, query response latencies, and hard spending caps to prevent budget overruns.

**Delivered Capabilities:**
1. **OpenTelemetry Telemetry & Tracing:**
   - `TelemetryMeter` emitting structured tracing spans across RAG query pipelines, retrieval stages, and LLM completions.
2. **Multi-Tenant Token Accounting:**
   - `TenantUsage` table tracking prompt, completion, and total tokens per tenant.
3. **Hard Monthly Budget Caps:**
   - Dynamic monthly budget caps per tenant with automated `HTTP 402 Payment Required` rejection upon budget exhaustion.
4. **Usage Export & Monitoring:**
   - Admin CSV telemetry exporter (`/telemetry/export`) and tenant usage breakdown metrics.

---

### Phase 12: Enterprise Single Sign-On (SSO) & SAML / OAuth2 🟡 Next Up
**Problem Statement:**  
Enterprise organizations require single sign-on tied to corporate identity providers (Google Workspace, Microsoft Entra ID / Azure AD, Okta, Ping Identity) rather than standalone username/password credentials.

**Planned Deliverables:**
1. **OAuth2 / OIDC & SAML 2.0 Integration:**
   - Implement OpenID Connect for Google Workspace and Microsoft Entra ID.
   - Add SAML 2.0 service provider (SP) support for enterprise IdPs (Okta, Ping Identity).
2. **Automatic Directory Group & Role Mapping:**
   - Automatically map corporate directory groups (e.g. `IT-Security`, `HR-Management`, `Engineering`) to application roles (`admin`, `editor`, `user`).
3. **Enterprise Session Revocation & Enforced MFA:**
   - Centralized session revocation webhooks and enforcement of identity provider multi-factor authentication (MFA) requirements.

---

## 🛠️ Immediate Recommended Action Plan

For the immediate next sprint, execute **Phase 12 (Enterprise SSO & SAML / OAuth2)**:
1. Implement OIDC/SAML authentication endpoints in `knowledge-bot/api/auth.py`.
2. Add IdP provider configuration (`SSO_PROVIDER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `SAML_METADATA_URL`) to `src/config.py`.
3. Create frontend SSO login buttons and OAuth2 callback handler page (`frontend/app/auth/callback/page.tsx`).
4. Implement automatic directory group-to-role synchronization.
