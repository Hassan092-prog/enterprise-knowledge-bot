# Knowledge Bot Backend API & RAG Engine

The core RAG (Retrieval-Augmented Generation) and Knowledge Graph engine for the Enterprise Knowledge Bot, powered by FastAPI, PostgreSQL, ChromaDB, MinIO S3 Object Storage, Celery, and NetworkX.

---

## 🌟 Capabilities & Features

- **Decoupled Architecture:** Runs with standalone **ChromaDB HTTP Server** (`CHROMA_HOST`, `CHROMA_PORT`), **MinIO S3 Object Storage**, **Redis 7**, and **PostgreSQL 15**.
- **Organization Multi-Tenancy:** Hardened tenant isolation across vector, database, object storage, BM25, and knowledge graph queries.
- **Role-Based Access Control (RBAC):** Dual-tier governance supporting Platform SuperAdmin (`is_platform_admin=True`), Tenant SuperAdmin, Tenant Admins, Editors, and standard Members.
- **Multi-Tenant Knowledge Graph:** Rule-based + LLM entity-relationship extractor, NetworkX in-memory ego-subgraph search, PostgreSQL relational graph durability, and hybrid graph fusion context injection.
- **Asynchronous Ingestion Stepper:** Celery background worker reports real-time ingestion states (`Parsing` $\rightarrow$ `Chunking` $\rightarrow$ `Summarizing` $\rightarrow$ `Embedding` $\rightarrow$ `Graph Extraction` $\rightarrow$ `Ready`) via `/tasks/{task_id}`.
- **Distributed Cloud Storage:** Pluggable `StorageProvider` interface (`LocalStorageProvider`, `S3StorageProvider`) with multi-tenant canonical keys and authenticated presigned URLs.
- **Advanced Hybrid Search:** Combines dense ChromaDB embeddings with sparse BM25 keyword matching via **Reciprocal Rank Fusion (RRF)**.
- **Query Expansion & Routing:** LLM-generated query variations and automatic routing for CSV tabular data to a dedicated Pandas Agent.
- **Cross-Encoder & MMR:** `ms-marco-MiniLM-L-6-v2` neural re-scoring and Jaccard-based Maximal Marginal Relevance diversity filtering.
- **Observability & Cost Governance:** OpenTelemetry tracing spans, tenant monthly token budgets, automatic `HTTP 402` enforcement, and CSV telemetry exports.
- **Multi-Provider LLM Factory:** Dynamic switching between OpenAI (`gpt-4o-mini`), Mistral (`mistral-small`), and Groq (`openai/gpt-oss-120b`).

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **API Framework** | FastAPI (Python 3.11) |
| **Relational Database** | PostgreSQL 15 (SQLAlchemy ORM) |
| **Vector Store** | ChromaDB (Standalone HTTP Server v0.5.20) |
| **Object Storage** | MinIO S3 (AWS SDK / Boto3 compatibility) |
| **Knowledge Graph** | NetworkX (In-Memory MultiDiGraph) + PostgreSQL Persistence |
| **Task Queue & Broker** | Celery 5 + Redis 7 |
| **RAG & Orchestration** | LangChain, Rank-BM25, Sentence-Transformers |
| **Document Parsers** | PyPDF, python-docx, Tesseract OCR (`pytesseract`, `pdf2image`) |
| **Observability** | OpenTelemetry, Prometheus-compatible telemetry metrics |

---

## 📁 Codebase Layout

```text
knowledge-bot/
├── api/
│   ├── admin.py            # Admin statistics, user roles, access requests, global docs
│   ├── auth.py             # User registration, JWT login, join-code verification, role requests
│   ├── dependencies.py     # Database session, tenant isolation & RBAC dependency injection
│   ├── graph.py            # Knowledge Graph endpoints (/stats, /subgraph, /entity, /rebuild, /clear)
│   ├── main.py             # Chat sessions, query execution, task polling (/tasks/{id})
│   ├── organizations.py    # Organization lifecycle, join codes, superadmin transfers
│   ├── platform.py         # Cross-tenant platform superadmin audit endpoints
│   └── telemetry.py        # Token consumption analytics & CSV usage exports
├── src/
│   ├── generation/
│   │   └── llm_chain.py    # Prompt templates, citation extraction, token streaming, graph fusion
│   ├── graph/
│   │   ├── base.py         # Abstract BaseGraphStore interface & data structures
│   │   ├── extractor.py    # Rule-based + LLM entity and relationship extraction
│   │   ├── fusion.py       # Ego-subgraph search & markdown graph context synthesis
│   │   └── networkx_store.py # Multi-tenant NetworkX graph store backed by PostgreSQL
│   ├── ingestion/
│   │   ├── chunker.py      # Recursive character text splitting
│   │   └── document_loader.py # Multi-format parsers (PDF, DOCX, TXT, CSV) with OCR fallback
│   ├── retrieval/
│   │   ├── retriever.py    # Facade: query expansion, RRF hybrid search, CrossEncoder, MMR
│   │   ├── router.py       # Query intent router (detects tabular CSV vs textual intent)
│   │   ├── summarizer.py   # Document executive summary generator
│   │   ├── tabular_agent.py# Pandas DataFrame query execution agent
│   │   └── vector_store.py # ChromaDB client interface (HTTP & persistent)
│   ├── storage/
│   │   ├── base.py         # StorageProvider abstract base interface
│   │   ├── local_storage.py# Local filesystem storage implementation
│   │   └── s3_storage.py   # MinIO / AWS S3 distributed object storage implementation
│   ├── telemetry/
│   │   └── meter.py        # OpenTelemetry tracing, tenant token accounting & budget caps
│   ├── config.py           # Centralized environment settings & startup validator
│   ├── database.py         # SQLAlchemy engine, session maker & bootstrap migrations
│   ├── llm_factory.py      # Dynamic LLM provider factory (OpenAI, Mistral, Groq)
│   ├── logger.py           # Structured logging configuration
│   ├── models.py           # Database models (Tenant, User, Node, Edge, Usage, Session, Message)
│   └── worker.py           # Celery application & asynchronous ingestion worker tasks
├── scripts/
│   ├── healthcheck.py      # Container liveness & readiness check probe
│   ├── migrate_local_to_s3.py # Migration tool to transfer local files to S3/MinIO
│   └── verify_multi_tenancy.py # Comprehensive 23-check multi-tenancy diagnostic suite
└── tests/
    ├── test_api.py         # API endpoints & session management tests
    ├── test_chunker.py     # Chunking correctness tests
    ├── test_document_loader.py # Multi-format loader tests
    ├── test_graph.py       # Knowledge Graph isolation, traversal & cascade deletion tests
    └── test_rag_evaluation.py # Quantitative RAG evaluation benchmarks
```

---

## ⚙️ Configuration & Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Database & Broker Connections
DATABASE_URL=postgresql://postgres:password@db:5432/chatdb
REDIS_URL=redis://redis:6379/0
CHROMA_HOST=chromadb
CHROMA_PORT=8000

# Object Storage Backend
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=http://minio:9000
S3_PUBLIC_ENDPOINT_URL=http://localhost:9010
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_NAME=enterprise-documents
S3_REGION=us-east-1

# Knowledge Graph Configuration
GRAPH_ENABLED=true
GRAPH_BACKEND=networkx
GRAPH_EXTRACTION_MODE=hybrid
GRAPH_MAX_HOPS=2
GRAPH_MAX_SUBGRAPH_NODES=30

# Observability & Telemetry
ENABLE_TELEMETRY=true

# LLM Provider Configuration ("openai", "mistral", or "groq")
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Security & Limits
SECRET_KEY=your_jwt_secret_key_here
MAX_FILE_SIZE_MB=50
MAX_QUERY_LENGTH=2000
```

---

## 🧪 Testing & Verification

Run the full unit and integration test suite:
```bash
pytest tests/test_chunker.py tests/test_document_loader.py tests/test_api.py tests/test_graph.py -v
```

Run the 23-check enterprise multi-tenancy diagnostic verification:
```bash
python scripts/verify_multi_tenancy.py
```

Run quantitative RAG quality evaluation benchmarks:
```bash
pytest tests/test_rag_evaluation.py -v
```
