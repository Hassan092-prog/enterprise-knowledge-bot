# Enterprise Knowledge Bot: Codebase Diagnosis & Technical State

**Audit Date:** October 2026  
**Repository:** `enterprise-knowledge-bot`  
**Current Branch:** `main`

---

## 1. Executive Summary & Verification

A comprehensive audit of the repository was performed across the backend (`knowledge-bot/`), frontend (`frontend/`), orchestrations (`docker-compose.yml`), and test suites. 

### Status of Previous Roadmap Recommendations
Previous diagnosis notes recommended three primary architectural enhancements. **All three have been successfully implemented in the active codebase:**
1. ✅ **Decoupled Vector Database:** Migrated from in-process local ChromaDB to a standalone HTTP server container (`chromadb/chroma:0.5.20` on port `8001`), consumed via `chromadb.HttpClient`.
2. ✅ **Asynchronous Task Queue:** Added Redis 7 (`knowledge-bot-redis`) and a dedicated Celery worker service (`knowledge-bot-worker` running `celery -A src.worker.celery_app worker`) to offload document ingestion and embedding.
3. ✅ **Query Expansion & Advanced Retrieval:** Implemented LLM-based query variation generation (`_expand_query`), Reciprocal Rank Fusion (RRF) between dense vector search and sparse BM25 search, Cross-Encoder re-ranking (`ms-marco-MiniLM-L-6-v2`), and MMR diversity filtering.

---

## 2. Complete Component-by-Component Diagnosis

### A. Container Orchestration (`docker-compose.yml`)
The platform has evolved from a 3-container model to a production **6-service container topology**:
- **`redis` (`redis:7-alpine`):** Broker and backend for Celery asynchronous tasks.
- **`db` (`postgres:15-alpine` on port 5433):** Relational persistence for user accounts, chat sessions, message histories, and access requests.
- **`chromadb` (`chromadb/chroma:0.5.20` on port 8001):** Persistent vector database server, mounted to `./knowledge-bot/chroma_data`.
- **`backend` (`knowledge-bot/Dockerfile` on port 8000):** FastAPI REST & SSE streaming server.
- **`worker` (`knowledge-bot/Dockerfile`):** Dedicated Celery worker process handling OCR, parsing, chunking, and embedding.
- **`frontend` (`frontend/Dockerfile` on port 3000):** Next.js 15 App Router web client.

### B. Ingestion & Preprocessing (`knowledge-bot/src/ingestion/`)
- **Parsers:** Supports `.pdf`, `.docx`, `.txt`, and `.csv`.
- **OCR Engine:** Scanned PDFs are automatically detected and processed with Tesseract OCR (`pytesseract` + `pdf2image`).
- **Executive Summaries:** Ingestion automatically generates an executive summary chunk for non-CSV documents and appends it to the vector store with metadata `is_summary: True`.
- **Chunking:** Context-preserving recursive character splitting (default 1,000 characters with 200-character overlap).

### C. Retrieval Pipeline (`knowledge-bot/src/retrieval/`)
- **Query Router:** Directs queries mentioning CSV files to a dedicated Pandas Tabular Agent (`run_tabular_query`) to ensure mathematical and aggregation accuracy.
- **Query Expansion:** `Retriever._expand_query()` prompts the configured LLM to generate 3 alternative query formulations to solve vocabulary mismatch.
- **Hybrid Retrieval:** Concurrently queries ChromaDB (dense) and BM25 (sparse) across all expanded query variations.
- **Reciprocal Rank Fusion (RRF):** Fuses ranking scores using $RRF(d) = \sum \frac{1}{60 + \text{rank}(d)}$.
- **Cross-Encoder Re-Ranking:** Scores top candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- **MMR Diversity Filtering:** Jaccard-based Maximal Marginal Relevance ($\lambda = 0.3$) filters out repetitive chunks.

### D. Multi-Provider LLM Engine (`knowledge-bot/src/llm_factory.py`)
Centralized factory providing plug-and-play switching:
- **OpenAI:** `gpt-4o-mini` + `text-embedding-3-small` (1536 dims).
- **Mistral:** `mistral-small-latest` + `mistral-embed` (1536 dims).
- **Groq:** `openai/gpt-oss-120b` + local HuggingFace `all-MiniLM-L6-v2` (384 dims).

### E. Security & Governance (`knowledge-bot/api/` & `src/models.py`)
- **Authentication:** JWT tokens signed with SHA-256 and bcrypt-hashed passwords.
- **3-Tier RBAC:** Supports `user`, `editor`, and `admin` roles.
- **Role Elevation Workflow:** Users submit requests to `/auth/request_role`, recorded in the `access_requests` table. Admins approve/reject via `/admin/requests/{id}/approve`.
- **Data Isolation:** User documents are strictly partitioned in ChromaDB by `user_id`. Global documents (`is_global=1`) are searchable by all authenticated users but can only be created or deleted by `admin` or `editor` roles.

### F. Frontend Application (`frontend/app/`)
- **Framework:** Next.js 15 (App Router), React 19, Tailwind CSS.
- **Chat Experience:** Real-time token streaming with Markdown, tables, and syntax-highlighted code blocks (`react-syntax-highlighter`).
- **Session Drawer:** Create, rename, delete, and switch between multiple chat conversations with server synchronization.
- **Document Manager:** Tabbed view of personal vs. global documents with file deletion and upload capabilities.
- **Document Mentions:** Interactive `@` / `!` menu for targeting specific files in queries or summaries.
- **Admin Portal (`/admin`):** System metrics, pending role requests approval interface, user list, and global document management.

---

## 3. Identified Gaps & Technical Debt

While the system is robust and feature-rich, the audit revealed concrete areas for refinement:

### 1. Ingestion Status Race Condition (High Priority)
- **Problem:** When a user uploads a file, `/upload` queues a Celery task and immediately returns `{"status": "processing", "task_id": task.id}`. However, the frontend (`frontend/app/page.tsx`, line 204) immediately displays a success toast and calls `fetchDocuments()`. 
- **Consequence:** Because Celery takes several seconds to parse, chunk, and embed, `fetchDocuments()` often runs before the worker has written to ChromaDB, leading to confusing UI behavior where uploaded files do not appear immediately without a manual refresh.
- **Remedy:** Implement a dedicated `/tasks/{task_id}` polling endpoint in FastAPI, and update the frontend with an active ingestion progress indicator.

### 2. Filesystem Storage Coupling (Medium Priority)
- **Problem:** Document files are saved to the local container disk (`UPLOAD_DIR`). The Celery worker and FastAPI backend must share this folder via Docker volume mounting.
- **Consequence:** In a multi-node Kubernetes or cloud deployment, local volume sharing becomes complex.
- **Remedy:** Integrate an S3-compatible object store (MinIO for on-premise or AWS S3 / Cloudflare R2).

### 3. Rate Limiting & API Hardening (Medium Priority)
- **Problem:** The FastAPI application currently configures CORS to allow all origins (`allow_origins=["*"]`) and lacks request rate limiting on the `/query` and `/upload` endpoints.
- **Remedy:** Add Redis-backed rate limiting (using `slowapi`) to protect expensive LLM and embedding endpoints from abuse, and restrict CORS to configured domains.

### 4. Observability & Tracing (Low to Medium Priority)
- **Problem:** Logs are written to standard output and local log files. There is no automated tracing for LLM latency, token expenditure per user, or retrieval evaluation metrics in production.
- **Remedy:** Integrate OpenTelemetry instrumentation with Langfuse or Arize Phoenix.

---

## 4. Structured Strategic Roadmap (Phases 8–12)

| Phase | Milestone | Objective | Key Deliverables |
|---|---|---|---|
| **Phase 8** | **Ingestion UX & Task Polling** | Real-time upload transparency | • FastAPI `/tasks/{task_id}` status endpoint<br>• Celery task state persistence (`PENDING`, `PROGRESS`, `SUCCESS`, `FAILURE`)<br>• Frontend progress stepper (Uploading → Parsing → Embedding → Ready) |
| **Phase 9** | **Distributed Object Storage** | Decouple files from local disks | • MinIO / S3 client integration<br>• Presigned URLs for secure uploads/downloads<br>• Eliminates Docker host volume synchronization dependencies |
| **Phase 10** | **Graph RAG & Entity Linking** | Multi-hop enterprise reasoning | • Extract entities and relationships during ingestion<br>• Knowledge graph backend (Neo4j or NetworkX)<br>• Combined Vector + Graph hybrid retrieval |
| **Phase 11** | **Enterprise SSO & SAML** | Corporate identity provider integration | • OAuth2 / OIDC (Google Workspace, Microsoft Entra ID)<br>• SAML 2.0 support for enterprise Okta integration<br>• Automatic directory group to RBAC role synchronization |
| **Phase 12** | **Production Observability & Tracing** | Cost, latency, and quality governance | • Langfuse / Phoenix OpenTelemetry integration<br>• Per-user token consumption tracking and budget caps<br>• Continuous RAGAS evaluation in staging pipelines |

---

## 5. How to Run & Verify the Active System

```bash
# 1. Build and start all 6 services
docker compose up --build -d

# 2. Check health of all containers
docker compose ps

# 3. Access interfaces:
# - Frontend: http://localhost:3000
# - Backend Swagger API: http://localhost:8000/docs
# - ChromaDB Heartbeat: http://localhost:8001/api/v1/heartbeat

# 4. Bootstrap the first user to Admin:
curl -X POST http://localhost:8000/admin/make_me_admin
```
