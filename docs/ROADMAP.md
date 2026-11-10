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
| **Phase 12** | **Enterprise SSO & SAML / OAuth2** | Corporate Identity Providers (Okta / Azure AD / OIDC) | ✅ **Completed** |

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

### Phase 12: Enterprise Single Sign-On (SSO) & SAML / OAuth2 ✅ Completed
**Problem Statement:**  
Enterprise organizations require single sign-on tied to corporate identity providers (Google Workspace, Microsoft Entra ID / Azure AD, Okta, Ping Identity) rather than standalone username/password credentials. Furthermore, enterprise security teams mandate corporate directory group synchronization, domain auto-routing, emergency session revocation, and SAML 2.0 assertions with X.509 signature verification.

**Delivered Capabilities:**
1. **Multi-Tenant SSO Model (`TenantSSOConfig`):**
   - Per-tenant SSO configuration stored in PostgreSQL (`tenant_sso_configs`) supporting SAML 2.0, OpenID Connect (OIDC), Okta, Entra ID, and Google Workspace.
   - Dynamic enforcement toggle (`enforce_sso`) disabling password login for corporate members to guarantee IdP compliance.
2. **Native SAML 2.0 Service Provider (SP) Engine:**
   - Pure-Python SAML 2.0 SP engine (`src/sso/saml.py`) utilizing `cryptography.x509` and `PKCS1v15` for signature validation without brittle C-bindings.
   - SP Metadata generation (`/auth/sso/saml/metadata`), deflated/base64 AuthnRequest builder (`/auth/sso/saml/login`), and ACS endpoint (`/auth/sso/saml/acs`) with fast-track XML metadata parsing (`/admin/sso/config`).
3. **Enterprise OIDC Engine:**
   - Dynamic `.well-known/openid-configuration` discovery, PKCE/state-protected authorization URL generation, and code exchange (`/auth/sso/oidc/authorize`, `/auth/sso/oidc/callback`).
4. **Corporate Directory Group to RBAC Role Mapping:**
   - `RoleMappingEngine` (`src/sso/base.py`) automatically maps IdP directory group claims (e.g., `IT-Security`, `Technical-Writers`) to application RBAC roles (`admin`, `editor`, `user`) with priority tiering (`admin > editor > user`).
5. **Zero-Friction Corporate Domain Auto-Discovery:**
   - `/auth/sso/discover?email=user@company.com` automatically resolves tenant configuration, matches allowed domains, and outputs the direct IdP login URL.
6. **Centralized Redis Session Revocation & Token Blacklist:**
   - High-performance session revocation engine (`src/sso/revocation.py`) backing `/auth/sso/revoke` and `/auth/logout`.
   - Invalidation by JTI or user/tenant revocation timestamp (`is_token_blacklisted`, `is_session_revoked`) integrated into `api/dependencies.py:get_current_user`.
7. **Enterprise Admin UI & Login Experience:**
   - **Frontend Login (`frontend/app/login/page.tsx`):** Seamless toggle between Credentials and Enterprise SSO with instant work email domain discovery.
   - **Auth Callback Handler (`frontend/app/auth/callback/page.tsx`):** Unified callback processing for OAuth2, SAML ACS redirects, and OIDC tokens.
   - **Admin Console (`frontend/app/admin/page.tsx`):** Dedicated "SSO & Directory Sync" tab with IdP metadata paste/upload, ACS endpoints copy tool, role mapping editor, and emergency session revocation.
8. **Automated Verification & Diagnostics:**
   - Added Check 24 to `knowledge-bot/scripts/verify_multi_tenancy.py` (24/24 diagnostic checks passed).
   - Dedicated unit test suite in `knowledge-bot/tests/test_sso.py` (8/8 tests passed; full test suite: 29/29 passed).

---

## 🛠️ Verification & Next Steps

All 12 core engineering phases have been implemented and verified with passing unit tests, end-to-end integration checks, and container builds. All future initiatives require explicit user authorization before execution.
