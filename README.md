# Enterprise RAG Knowledge Bot

A production-grade, multi-tenant RAG (Retrieval-Augmented Generation) platform designed for secure enterprise document search, question answering, and tabular data analytics. 

Built with **Next.js 15**, **FastAPI**, **PostgreSQL**, **Standalone ChromaDB**, **Redis**, and **Celery**, it enables isolated personal document sandboxes, organization-wide global document management, advanced hybrid retrieval with cross-encoder re-ranking, and automated query routing.

---

## 🎯 What this Project Is About (The Use Case)

In modern enterprise environments, employees constantly interact with two distinct classes of information:
1. **Global Organizational Knowledge:** Company handbooks, HR policies, engineering standards, and standard operating procedures (SOPs).
2. **Confidential / Personal Documents:** Team-specific drafts, proprietary datasets, customer notes, and sensitive financial reports.

Standard consumer AI tools (like public ChatGPT) pose serious compliance and data leakage risks and cannot guarantee document-level isolation or multi-tenant security.

**This project solves this by providing:**
1. **True Multi-Tenant Isolation:** Documents uploaded by an individual are tagged with their unique `user_id` in ChromaDB and PostgreSQL. Users cannot query, view, or infer other users' documents.
2. **Admin-Governed Global Knowledge Base:** Administrators and Editors manage verified company-wide documents. When users query the assistant, the RAG engine queries both their personal sandbox and global repositories simultaneously.
3. **Cited & Grounded Answers:** Prevents hallucinations by surfacing strict citations referencing source documents, chunk IDs, and page numbers.
4. **Intelligent Tabular Data Routing:** Directly queries CSV datasets using a dedicated Pandas Data Analysis Agent, eliminating vector approximation errors for numerical calculations and aggregations.
5. **Decoupled Asynchronous Processing:** Ingestion tasks (parsing, OCR, chunking, embedding) are processed asynchronously via Celery workers and Redis queues, preventing API timeouts on large file uploads.

---

## 🚀 Key Features & Implemented Capabilities

### 🧠 Advanced RAG & Retrieval Engine
- **LLM Query Expansion:** Generates multiple synonymous queries to bridge vocabulary mismatch between user questions and stored document chunks.
- **RRF Hybrid Search:** Combines dense semantic vector retrieval (ChromaDB) and sparse keyword retrieval (BM25) using **Reciprocal Rank Fusion (RRF)**.
- **Cross-Encoder Re-Ranking:** Re-scores retrieved candidate chunks using `cross-encoder/ms-marco-MiniLM-L-6-v2` for precise semantic alignment.
- **Maximal Marginal Relevance (MMR):** Applies Jaccard-based diversity filtering to penalize repetitive information and maximize answer coverage.
- **Executive Document Summaries:** Automatically generates an executive summary chunk upon ingestion for immediate high-level document overviews.
- **Multi-Provider LLM Support:** Factory architecture supporting **OpenAI** (`gpt-4o-mini`, `text-embedding-3-small`), **Mistral** (`mistral-small-latest`, `mistral-embed`), and **Groq** (`gpt-oss-120b`, local `all-MiniLM-L6-v2` embeddings).

### 📄 Ingestion & Document Processing
- **Multi-Format Parsing:** Supports `.pdf`, `.docx`, `.txt`, and `.csv`.
- **OCR Fallback:** Scanned or image-only PDFs automatically fallback to OCR processing via Tesseract (`pytesseract` + `pdf2image`).
- **Semantic Chunking:** Context-aware recursive character chunking with configurable overlap.
- **Async Ingestion Pipeline:** Offloaded to a dedicated **Celery Worker** running against **Redis**, enabling fast, non-blocking uploads.

### 🔒 Enterprise Security & Governance
- **Multi-Tenant Isolation:** Dynamic metadata filtering on vector and relational database queries.
- **3-Tier RBAC:** `user`, `editor`, and `admin` roles.
- **Role Elevation Requests:** Built-in workflow allowing users to request elevated roles, with admin review and one-click approval/rejection.
- **Dedicated Admin Console:** Comprehensive admin interface for managing global enterprise documents, monitoring system statistics, and governing user permissions.

### 💻 Modern Web Experience
- **Next.js 15 & React 19:** Built with the App Router, TailwindCSS, and dark-mode native interface.
- **Real-Time Markdown Streaming:** Token-by-token response streaming with live Markdown rendering, formatted tables, and Prism code syntax highlighting.
- **Document Mentions (`!filename`):** Interactive tagging menu allowing users to direct questions or summarization requests to specific files.
- **Chat Session Persistence:** Multi-chat session management (create, rename, switch, delete) persisted in PostgreSQL.

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
                                  │     Port: 8000 (Python 3)     │
                                  └───┬───────────┬───────────┬───┘
                                      │           │           │
                     ┌────────────────┘           │           └────────────────┐
                     │ Async Upload Tasks         │ Queries                    │ Relational Data
                     ▼                            ▼                            ▼
        ┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
        │       Redis 7 Queue     │  │  ChromaDB Standalone    │  │  PostgreSQL 15 Database │
        │       Port: 6379        │  │  Port: 8001 (HTTP API)  │  │  Port: 5433 (chatdb)    │
        └────────────┬────────────┘  └────────────┬────────────┘  └─────────────────────────┘
                     │                            │
                     ▼                            │
        ┌─────────────────────────┐               │
        │   Celery Worker Process │───────────────┘
        │ (OCR, Chunk, Embed, Ingest)
        └─────────────────────────┘
```

### Retrieval & Generation Dataflow

```text
User Query
    │
    ▼
Auth Verification (JWT)
    │
    ▼
Query Router ───────────────────(CSV Target)────────────► Pandas Tabular Agent ──────┐
    │                                                                                │
    ▼ (Text Target)                                                                 │
Query Expansion (LLM generates 3 query variants)                                     │
    │                                                                                │
    ▼                                                                                │
Hybrid Search (Dense ChromaDB + Sparse BM25)                                         │
    │                                                                                │
    ▼                                                                                │
Reciprocal Rank Fusion (RRF) -> Candidate Pool                                       │
    │                                                                                │
    ▼                                                                                │
Cross-Encoder Re-Ranking (ms-marco-MiniLM-L-6-v2)                                    │
    │                                                                                │
    ▼                                                                                │
MMR Diversity Filtering (λ = 0.3)                                                    │
    │                                                                                │
    ▼                                                                                │
Context Assembly + System Prompt                                                     │
    │                                                                                │
    ▼                                                                                │
LLM Generation (OpenAI / Mistral / Groq)                                             │
    │                                                                                │
    ▼                                                                                ▼
Token Streaming Response (SSE) ◄─────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack & Service Matrix

| Service | Container Name | Port | Description |
|---|---|---|---|
| **Frontend** | `knowledge-bot-frontend` | `3000` | Next.js 15, React 19, TailwindCSS, Markdown Streaming |
| **Backend API** | `knowledge-bot-backend` | `8000` | FastAPI, Pydantic, SQLAlchemy, LangChain |
| **Worker** | `knowledge-bot-worker` | Internal | Celery worker executing background ingestion pipelines |
| **Queue** | `knowledge-bot-redis` | `6379` | Redis 7 broker and task result backend |
| **Vector DB** | `knowledge-bot-chromadb` | `8001` | Standalone ChromaDB HTTP server (v0.5.20) |
| **Database** | `knowledge-bot-db` | `5433` | PostgreSQL 15 storing users, sessions, messages, and role requests |

---

## 📦 Setup & Deployment

The entire system is orchestrated via Docker Compose.

### 1. Clone the repository
```bash
git clone https://github.com/Hassan092-prog/enterprise-knowledge-bot.git
cd enterprise-knowledge-bot
```

### 2. Configure Environment Variables
Copy the example configuration to `.env` in `knowledge-bot/`:
```bash
cp knowledge-bot/.env.example knowledge-bot/.env
```

Configure your LLM provider and credentials in `knowledge-bot/.env`:
```env
# Provider choice: "openai", "mistral", or "groq"
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here

# Or for Mistral:
# LLM_PROVIDER=mistral
# MISTRAL_API_KEY=your_mistral_api_key_here

# Or for Groq:
# LLM_PROVIDER=groq
# GROQ_API_KEY=your_groq_api_key_here
```

### 3. Build and Run Containers
```bash
docker compose up --build -d
```

Verify that all 6 services are healthy:
```bash
docker compose ps
```

### 4. Access the Application
- **Web Application UI:** [http://localhost:3000](http://localhost:3000)
- **FastAPI Interactive Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ChromaDB API Heartbeat:** [http://localhost:8001/api/v1/heartbeat](http://localhost:8001/api/v1/heartbeat)

### 5. Bootstrap Initial Admin Account
1. Open the UI at `http://localhost:3000` and register your initial account.
2. Promote this user to Admin by triggering the one-time bootstrap endpoint:
   ```bash
   curl -X POST http://localhost:8000/admin/make_me_admin
   ```
3. Refresh the web UI. You will now see the **Admin** shield icon in the top header, granting access to global document controls and user role governance.

---

## 📁 Repository Structure

```text
.
├── docker-compose.yml              # Orchestrates Frontend, Backend, Worker, Redis, Postgres, ChromaDB
├── docs/                           # Comprehensive technical documentation & roadmap
│   ├── ARCHITECTURE.md             # In-depth architectural design, schemas & dataflow
│   └── ROADMAP.md                  # Strategic engineering roadmap & upcoming phases
├── frontend/                       # Next.js 15 Web Application
│   ├── app/
│   │   ├── admin/                  # Admin dashboard (stats, role approvals, global docs)
│   │   ├── login/                  # Authentication page
│   │   ├── register/               # User registration page
│   │   ├── globals.css             # Design tokens & styling
│   │   └── page.tsx                # Main chat, session drawer, document manager, mention menu
│   ├── Dockerfile                  # Next.js standalone container build
│   └── package.json
├── knowledge-bot/                  # FastAPI Backend & Core Engine
│   ├── api/
│   │   ├── admin.py                # Admin statistics, user roles, access requests, global docs
│   │   ├── auth.py                 # JWT authentication, login, registration, role requests
│   │   ├── dependencies.py         # DB session & RBAC dependency injection
│   │   └── main.py                 # Chat sessions, query execution, async upload endpoints
│   ├── src/
│   │   ├── generation/             # LLM chains, prompts, streaming logic
│   │   ├── ingestion/              # Multi-format loaders (PDF+OCR, DOCX, TXT, CSV), chunker
│   │   ├── retrieval/              # Hybrid search, CrossEncoder reranking, MMR, router, vector store
│   │   ├── config.py               # Central configuration & environment validations
│   │   ├── database.py             # SQLAlchemy engine & session factory
│   │   ├── llm_factory.py          # Dynamic LLM provider factory (OpenAI, Mistral, Groq)
│   │   ├── models.py               # SQLAlchemy models (User, ChatSession, ChatMessage, AccessRequest)
│   │   └── worker.py               # Celery application & asynchronous ingestion worker tasks
│   ├── tests/                      # Unit tests & RAG evaluation suites (RAGAS / custom)
│   ├── Dockerfile                  # Backend & Worker container build
│   └── requirements.txt
├── project_diagnosis.md            # Verified project status diagnosis & technical state
└── test_data/                      # Curated test files (TXT, CSV) for verification
```

---

## 🗺️ Roadmap & Next Steps

See [docs/ROADMAP.md](file:///docs/ROADMAP.md) for full engineering specifications. Upcoming milestones include:
- **Phase 8: Ingestion Progress UX:** Task status endpoint (`/tasks/{task_id}`) and real-time upload progress polling in the UI.
- **Phase 9: Distributed Object Storage:** Migration from local upload mounts to S3/MinIO bucket storage.
- **Phase 10: Graph RAG:** Entity-relationship graph indexing for complex cross-document reasoning.
- **Phase 11: Enterprise SSO:** SAML 2.0 / OAuth2 (Azure AD / Okta / Google Workspace) integration.
- **Phase 12: Production Observability:** OpenTelemetry tracing, Langfuse telemetry, and Prometheus/Grafana dashboards.

---

## 👨‍💻 Author & Contributions

Built by Mohammed Hassan — B.E. AIML, MJCET Hyderabad  
- **GitHub:** [@Hassan092-prog](https://github.com/Hassan092-prog)
- **Project Repository:** [enterprise-knowledge-bot](https://github.com/Hassan092-prog/enterprise-knowledge-bot)
