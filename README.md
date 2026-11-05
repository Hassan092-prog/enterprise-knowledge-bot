# Enterprise RAG Knowledge Bot

A production-grade, multi-tenant RAG (Retrieval-Augmented Generation) and Knowledge Graph platform designed for secure enterprise document search, question answering, tabular data analytics, and multi-hop relationship reasoning.

Built with **Next.js 15**, **FastAPI**, **PostgreSQL 15**, **Standalone ChromaDB**, **MinIO S3 Object Storage**, **Redis 7**, **Celery**, and **NetworkX**, it provides strict corporate tenant isolation, organization-level global document governance, hybrid vector + sparse + graph retrieval with neural cross-encoder re-ranking, and real-time ingestion transparency.

---

## 🎯 Enterprise Use Case & Governance

In enterprise environments, corporate intelligence is distributed across unstructured policies, tabular data spreadsheets, and complex relational graphs:
1. **Organization-Level Multi-Tenancy:** Complete tenant boundary isolation across PostgreSQL, ChromaDB, S3 Object Storage, BM25, and Knowledge Graph.
2. **Dual-Tier Role Hierarchy:** 
   - **Platform SuperAdmin:** Cross-tenant health and audit visibility (`/platform-admin`).
   - **Tenant SuperAdmin:** Single organization owner with member management and atomic ownership transfer.
   - **Tenant Admin & Editor:** Global organizational corpus governance (`is_global=1`).
   - **Tenant Member (`user`):** Sandboxed private document uploads and unified querying.
3. **Cited & Grounded Answers:** Hallucination prevention surfacing exact source filenames, chunk IDs, page numbers, and interactive **Graph Link** entity citation badges.
4. **Intelligent Tabular Data Routing:** Automatic routing of CSV datasets to an in-memory Pandas Data Analysis Agent for exact mathematical aggregations.
5. **Decoupled Asynchronous Processing:** File parsing, OCR, chunking, embedding, and entity-relation extraction run asynchronously on Celery workers backed by Redis.

---

## 🚀 Key Features & Implemented Capabilities

### 🧠 Advanced Hybrid RAG & Knowledge Graph
- **Hybrid Retrieval Fusion:** Concurrently queries dense semantic embeddings (ChromaDB) and sparse lexical matching (BM25) using **Reciprocal Rank Fusion (RRF)**.
- **Knowledge Graph RAG Engine:** Hybrid regex and LLM entity-relation extractor indexes entities (`INCIDENT`, `SYSTEM`, `POLICY`, etc.) into an in-memory **NetworkX** `MultiDiGraph` backed by PostgreSQL. BFS ego-subgraph traversals enrich generation prompts with structured relationship context.
- **Neural Cross-Encoder Re-Ranking:** Re-scores top candidate chunks with `cross-encoder/ms-marco-MiniLM-L-6-v2` for maximum contextual precision.
- **Maximal Marginal Relevance (MMR):** Applies Jaccard-based diversity filtering ($\lambda = 0.3$) to penalize redundant information.
- **LLM Query Expansion:** Synthesizes 3 synonymous search queries to eliminate vocabulary mismatches.
- **Executive Summaries:** Generates and indexes high-level document overviews on ingestion.
- **Multi-Provider LLM Factory:** Supports **OpenAI** (`gpt-4o-mini`, `text-embedding-3-small`), **Mistral** (`mistral-small-latest`, `mistral-embed`), and **Groq** (`gpt-oss-120b`, local `all-MiniLM-L6-v2`).

### 📦 Distributed Storage & Ingestion Transparency
- **MinIO / S3 Distributed Object Storage:** Documents are stored under multi-tenant canonical keys (`tenants/{tenant_id}/...`) with authenticated presigned download URLs.
- **Real-Time Ingestion Stepper:** Asynchronous worker reports step-by-step progress (`Parsing` $\rightarrow$ `Chunking` $\rightarrow$ `Summarizing` $\rightarrow$ `Embedding` $\rightarrow$ `Indexed`), polled via `/tasks/{task_id}`.
- **Multi-Format Ingestion:** Parsers for `.pdf`, `.docx`, `.txt`, and `.csv` with automatic Tesseract OCR fallback for scanned documents.

### 📊 Observability & Cost Governance
- **OpenTelemetry Instrumentation:** Structured telemetry traces track latency across retrieval, graph expansion, and generation.
- **Tenant Token Accounting:** Real-time metering of prompt, completion, and total tokens per organization.
- **Hard Monthly Budget Caps:** Organizations enforce monthly spending limits with automatic `HTTP 402 Payment Required` rejection upon budget exhaustion.
- **CSV Telemetry Exporter:** One-click telemetry data exports for organization admins.

### 💻 Modern Web Experience (Next.js 15 & React 19)
- **Precision Dossier UI Architecture:** Calibrated OKLCH dark graphite design, 1px structural hairlines, Archival Brass citations, Emerald SQL chips, and Violet Graph badges.
- **Token Streaming Response:** Real-time Server-Sent Events (SSE) streaming with live Markdown rendering, tables, and Prism code syntax highlighting.
- **Dual Mention Autocomplete:** Interactive autocomplete menu targeting specific global documents (`@filename`) or private documents (`!filename`).
- **Knowledge Graph Explorer:** Dedicated Admin tab for inspecting nodes, relationship edges, and ego-subgraphs.

---

## 🏗️ System Architecture

```text
                                  ┌───────────────────────────────┐
                                  │      Next.js 15 Frontend      │
                                  │   (React 19, Tailwind CSS)    │
                                  │     Port: 3000 (Dark UI)      │
                                  └───────────────┬───────────────┘
                                                  │ REST / SSE
                                                  ▼
                                  ┌───────────────────────────────┐
                                  │      FastAPI Backend API      │
                                  │     Port: 8000 (Python 3.11)  │
                                  └───┬───────────┬───────────┬───┘
                                      │           │           │
                     ┌────────────────┘           │           └────────────────┐
                     │ Async Ingestion Tasks      │ Vector & Graph Queries     │ Persistent Records
                     ▼                            ▼                            ▼
        ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
        │       Redis 7 Queue     │  │  ChromaDB Standalone    │  │  PostgreSQL 15 Database │
        │       Port: 6379        │  │  Port: 8001 (HTTP API)  │  │  Port: 5433 (chatdb)    │
        └────────────┬────────────┘  └────────────┬────────────┘  └────────────┬────────────┘
                     │                            │                            │
                     ▼                            │                            │
        ┌─────────────────────────┐               │                            │
        │   Celery Worker Process │───────────────┴────────────────────────────┤
        │ (OCR, Chunk, KG, Embed) │                                            │
        └────────────┬────────────┘                                            │
                     │                                                         │
                     ▼ Read/Write Files                                        │
        ┌─────────────────────────┐                                            │
        │  MinIO S3 Object Store  │◄───────────────────────────────────────────┘
        │  Ports: 9010 / 9011     │ (Presigned URLs & Canonical Buckets)
        └─────────────────────────┘
```

---

## 🛠️ Tech Stack & Service Matrix

| Service | Container Name | Port | Description |
|---|---|---|---|
| **Frontend** | `knowledge-bot-frontend` | `3000` | Next.js 15, React 19, Tailwind CSS v4, SSE Streaming |
| **Backend API** | `knowledge-bot-backend` | `8000` | FastAPI, Pydantic, SQLAlchemy, LangChain, OpenTelemetry |
| **Worker** | `knowledge-bot-worker` | Internal | Celery worker executing OCR, chunking, embedding, and KG extraction |
| **Queue** | `knowledge-bot-redis` | `6379` | Redis 7 broker and task result backend |
| **Vector DB** | `knowledge-bot-chromadb` | `8001` | Standalone ChromaDB HTTP server (v0.5.20) |
| **Database** | `knowledge-bot-db` | `5433` | PostgreSQL 15 (tenants, users, sessions, knowledge graph, usage) |
| **Object Storage**| `knowledge-bot-minio` | `9010` (API) / `9011` (Console) | MinIO S3-compatible cloud object store |

---

## 📁 Repository Structure

```text
.
├── docker-compose.yml              # 7-service orchestration (Frontend, Backend, Worker, Redis, DB, Chroma, MinIO)
├── docs/                           # Architecture, security specifications & milestones
│   ├── ARCHITECTURE.md             # In-depth architectural design, schemas, and dataflow
│   ├── ROADMAP.md                  # Strategic engineering roadmap & upcoming phases
│   └── multi_tenancy_implementation_plan.md # Multi-tenant security audit & isolation design
├── frontend/                       # Next.js 15 Web Application
│   ├── app/
│   │   ├── admin/                  # Admin dashboard (metrics, role approvals, global docs, Knowledge Graph tab)
│   │   ├── auth/callback/          # OAuth2 / SSO authentication callback handler
│   │   ├── login/                  # User login page
│   │   ├── platform-admin/         # Cross-tenant platform superadmin portal
│   │   ├── register/               # Organization onboarding & employee registration
│   │   ├── globals.css             # Design tokens & styling
│   │   └── page.tsx                # Chat, session drawer, document manager, live stepper, mention menu
│   ├── Dockerfile                  # Next.js standalone container build
│   └── package.json
├── knowledge-bot/                  # FastAPI Backend & Core Engine
│   ├── api/
│   │   ├── admin.py                # Admin statistics, user roles, access requests, global docs
│   │   ├── auth.py                 # JWT authentication, login, registration, role requests
│   │   ├── dependencies.py         # DB session, tenant isolation & RBAC dependencies
│   │   ├── graph.py                # Knowledge Graph endpoints (/stats, /subgraph, /entity, /rebuild)
│   │   ├── main.py                 # Chat sessions, query execution, task polling (/tasks/{id})
│   │   ├── organizations.py        # Organization lifecycle, join codes, superadmin transfers
│   │   ├── platform.py             # Platform superadmin cross-tenant audit endpoints
│   │   └── telemetry.py            # Token consumption analytics & CSV usage exports
│   ├── src/
│   │   ├── generation/             # LLM chains, prompts, streaming logic, graph context fusion
│   │   ├── graph/                  # NetworkX in-memory store, entity extractor, hybrid fusion
│   │   ├── ingestion/              # Multi-format loaders (PDF+OCR, DOCX, TXT, CSV), chunker
│   │   ├── retrieval/              # Hybrid search, CrossEncoder reranking, MMR, router, vector store
│   │   ├── storage/                # Pluggable storage providers (LocalStorageProvider, S3StorageProvider)
│   │   ├── telemetry/              # OpenTelemetry meter, token accounting, budget enforcement
│   │   ├── config.py               # Central configuration & environment validations
│   │   ├── database.py             # SQLAlchemy engine & session factory
│   │   ├── llm_factory.py          # Dynamic LLM provider factory (OpenAI, Mistral, Groq)
│   │   ├── models.py               # SQLAlchemy models (Tenant, User, Node, Edge, Usage, etc.)
│   │   └── worker.py               # Celery application & asynchronous ingestion worker tasks
│   ├── scripts/
│   │   ├── healthcheck.py          # Container health check probe
│   │   ├── migrate_local_to_s3.py  # Local disk to MinIO S3 object migration tool
│   │   └── verify_multi_tenancy.py # Comprehensive 23-check multi-tenancy diagnostic suite
│   ├── tests/                      # Unit, API, and Knowledge Graph test suites
│   ├── Dockerfile                  # Backend & Worker container build
│   └── requirements.txt
└── test_data/                      # Curated test files (TXT, CSV) for verification
```

---

## 📦 Setup & Deployment

The entire system is orchestrated via Docker Compose.

### 1. Configure Environment Variables
Copy the example configuration to `.env` in `knowledge-bot/`:
```bash
cp knowledge-bot/.env.example knowledge-bot/.env
```

Configure your LLM provider and credentials in `knowledge-bot/.env`:
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
```

### 2. Build and Run Containers
```bash
docker compose up --build -d
```

Verify that all 7 services are healthy:
```bash
docker compose ps
```

### 3. Access the Application
- **Web Application UI:** [http://localhost:3000](http://localhost:3000)
- **FastAPI Interactive Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ChromaDB API Heartbeat:** [http://localhost:8001/api/v1/heartbeat](http://localhost:8001/api/v1/heartbeat)
- **MinIO Storage Console:** [http://localhost:9011](http://localhost:9011)

---

## 🗺️ Roadmap & Current Status

| Milestone | Status | Description |
|---|:---:|---|
| **Phase 1: Ingestion Engine** | ✅ **Completed** | PDF+OCR, DOCX, TXT, CSV parsing |
| **Phase 2: Hybrid Vector Store** | ✅ **Completed** | ChromaDB, BM25, and metadata indexing |
| **Phase 3: Tabular Agent** | ✅ **Completed** | In-memory Pandas agent for CSV math |
| **Phase 4: Citations & Streaming** | ✅ **Completed** | LangChain prompt chains, executive summaries |
| **Phase 5: Relational DB & Auth** | ✅ **Completed** | PostgreSQL 15, JWT authentication, sessions |
| **Phase 6: Next.js 15 Frontend** | ✅ **Completed** | React 19, Markdown SSE streaming, mentions |
| **Phase 7: Advanced Retrieval** | ✅ **Completed** | Standalone ChromaDB, Celery + Redis, RRF, CrossEncoder, MMR |
| **Phase 8: Ingestion Transparency** | ✅ **Completed** | Real-time upload status & task polling stepper |
| **Phase 9: Distributed S3 Storage** | ✅ **Completed** | Decoupled cloud document storage & presigned URLs |
| **Phase 10: Graph RAG Engine** | ✅ **Completed** | Multi-tenant NetworkX/PostgreSQL Graph Store & Subgraph Fusion |
| **Phase 11: Observability & Cost** | ✅ **Completed** | OpenTelemetry spans, tenant token accounting & budget caps |
| **Phase 12: Enterprise SSO & SAML** | 🟡 **Next Up** | Corporate Identity Providers (Okta / Azure AD / OIDC) |

---

## 👨‍💻 Author & Contributions

Built by Mohammed Hassan — B.E. AIML, MJCET Hyderabad  
- **GitHub:** [@Hassan092-prog](https://github.com/Hassan092-prog)  
- **Project Repository:** [enterprise-knowledge-bot](https://github.com/Hassan092-prog/enterprise-knowledge-bot)
