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
| **Phase 8** | **Ingestion Transparency & Polling** | Real-time upload status & task polling | 🟡 **Next Up** |
| **Phase 9** | **Distributed Object Storage (MinIO/S3)** | Decoupled cloud document storage | 📋 Planned |
| **Phase 10** | **Graph RAG & Entity Relationships** | Knowledge Graph integration (Neo4j) | 📋 Planned |
| **Phase 11** | **Enterprise SSO & SAML / OAuth2** | Corporate Identity Providers (Okta/Azure) | 📋 Planned |
| **Phase 12** | **Observability & Cost Governance** | OpenTelemetry, Langfuse, rate limiting | 📋 Planned |

---

## 🎯 Detailed Future Roadmap (Phases 8–12)

### Phase 8: Ingestion Transparency & Task Polling (High Priority)
**Problem Statement:**  
Currently, `/upload` queues an asynchronous Celery task and immediately returns a `task_id`. However, the frontend immediately displays a success toast and calls `fetchDocuments()`, creating a race condition where the document has not yet been processed by the worker.

**Engineering Deliverables:**
1. **Backend Status Endpoint (`/tasks/{task_id}`):**
   - Implement FastAPI route querying Celery's `AsyncResult`:
     ```python
     @app.get("/tasks/{task_id}")
     def get_task_status(task_id: str):
         result = celery_app.AsyncResult(task_id)
         return {
             "task_id": task_id,
             "status": result.status, # PENDING, PROGRESS, SUCCESS, FAILURE
             "result": result.result if result.ready() else None
         }
     ```
2. **Worker Progress Reporting:**
   - Update `process_document` in `src/worker.py` to record step-by-step progress states: `Parsing` $\rightarrow$ `Chunking` $\rightarrow$ `Summarizing` $\rightarrow$ `Embedding` $\rightarrow$ `Indexed`.
3. **Frontend Ingestion Stepper:**
   - Replace the instant success notification with an active processing badge in the Document Manager sidebar.
   - Poll `/tasks/{task_id}` every 2 seconds until `SUCCESS` is returned, then automatically refresh the document list.

---

### Phase 9: Distributed Object Storage (S3 / MinIO Integration)
**Problem Statement:**  
Document files are currently written to local disk directories (`data/uploads`) mounted via Docker volumes. In multi-node cloud deployments (e.g. AWS ECS, EKS, or Kubernetes), local volume sharing between API nodes and worker pods is brittle and limits horizontal scaling.

**Engineering Deliverables:**
1. **S3 / MinIO Storage Backend:**
   - Abstract document storage behind a `StorageProvider` interface (`LocalStorageProvider`, `S3StorageProvider`).
   - Add MinIO container to `docker-compose.yml` for local development.
2. **Presigned Upload URLs:**
   - Frontend uploads files directly to object storage using short-lived presigned PUT URLs, reducing load on FastAPI workers.
3. **Worker Stream Processing:**
   - Celery workers read directly from S3/MinIO bucket buffers during parsing.

---

### Phase 10: Graph RAG & Knowledge Graph Engine
**Problem Statement:**  
Vector similarity struggles with complex, multi-hop queries spanning multiple documents (e.g., *"Which departments comply with the security policy changes enacted after Incident Report 104?"*). 

**Engineering Deliverables:**
1. **Entity & Relation Extraction:**
   - Use an LLM pipeline during document ingestion to identify entities (Users, Departments, Systems, Policies) and relations (`GOVERNED_BY`, `RESPONSIBLE_FOR`, `AFFECTS`).
2. **Graph Database Integration:**
   - Integrate Neo4j or FalkorDB into the backend stack.
3. **Graph + Vector Hybrid Retrieval:**
   - Combine graph traversal (finding connected entities) with vector similarity (finding contextual nuances) to answer cross-organizational enterprise queries.

---

### Phase 11: Enterprise Single Sign-On (SSO) & Directory Sync
**Problem Statement:**  
Enterprise organizations require single sign-on tied to corporate directories rather than standalone username/password credentials.

**Engineering Deliverables:**
1. **OAuth2 / OIDC & SAML 2.0:**
   - Implement OpenID Connect for Google Workspace and Microsoft Entra ID (Azure AD).
   - Add SAML 2.0 support for enterprise identity providers (Okta, Ping Identity).
2. **Automatic Directory Group Sync:**
   - Automatically map corporate directory groups (e.g. `IT-Admins`, `HR-Managers`) to application roles (`admin`, `editor`, `user`).
3. **Session Revocation & MFA:**
   - Enforce corporate MFA requirements and centralized token revocation.

---

### Phase 12: Production Observability, Cost Governance & Hardening
**Problem Statement:**  
Enterprise deployment requires deep visibility into token usage, cost per tenant, response latencies, and protection against denial-of-service or prompt abuse.

**Engineering Deliverables:**
1. **Tracing & Telemetry (OpenTelemetry + Langfuse):**
   - Instrument RAG chains with Langfuse or Arize Phoenix to trace query latency, token usage, and retrieval recall per user.
2. **Rate Limiting & Abuse Prevention:**
   - Add Redis-backed sliding window rate limiters (`slowapi`) on `/query` (e.g., max 30 queries/minute per user) and `/upload` (max 10 files/hour).
   - Configure strict CORS origin allowlists for production deployment.
3. **Tenant Cost Budgets:**
   - Track token consumption per `user_id` and enforce organizational spending limits.
4. **Automated CI/CD Evaluation:**
   - Run `test_rag_evaluation.py` on pull requests to enforce minimum RAGAS thresholds (Faithfulness $\ge 0.85$, Context Precision $\ge 0.70$).

---

## 🛠️ Immediate Recommended Action Plan

For the immediate next sprint, execute **Phase 8**:
1. Add `/tasks/{task_id}` in `knowledge-bot/api/main.py`.
2. Enhance `src/worker.py` to update task state during document processing.
3. Update `frontend/app/page.tsx` to handle the asynchronous task poll loop and display live progress badges.
