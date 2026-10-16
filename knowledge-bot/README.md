# Knowledge Bot Backend API & RAG Engine

The core RAG (Retrieval-Augmented Generation) engine and high-performance REST API for the Enterprise Knowledge Bot.

---

## 🌟 Capabilities & Features

- **Decoupled Architecture:** Designed to run with a standalone **ChromaDB HTTP Server** (`CHROMA_HOST`, `CHROMA_PORT`) and **PostgreSQL** relational database.
- **Asynchronous Ingestion Queue:** Offloads intensive document parsing, OCR, chunking, and embedding to background **Celery workers** backed by **Redis**.
- **Multi-Tenant Security:** Automatic isolation of documents at the vector store and relational database layer using `user_id` and `is_global` tags.
- **3-Tier RBAC:** Native support for `user`, `editor`, and `admin` roles, complete with role elevation requests and approval APIs.
- **Advanced Hybrid Search:** Combines dense ChromaDB embeddings with sparse BM25 keyword matching via **Reciprocal Rank Fusion (RRF)**.
- **Query Expansion:** LLM-powered generation of search variations to overcome vocabulary mismatches.
- **Cross-Encoder Re-Ranking:** Neural re-scoring using `cross-encoder/ms-marco-MiniLM-L-6-v2` to deliver peak context precision.
- **Maximal Marginal Relevance (MMR):** Algorithmic diversity filtering to eliminate redundant context chunks.
- **Document Summaries:** Generates and indexes executive summary chunks upon document ingestion.
- **Tabular Data Agent:** Dynamically routes `.csv` queries to an in-memory Pandas agent for precise calculations and aggregations.
- **Multi-Provider LLM Factory:** Supports OpenAI (`gpt-4o-mini`), Mistral (`mistral-small`), and Groq (`openai/gpt-oss-120b`).

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| **API Framework** | FastAPI (Python 3.11) |
| **Relational Database** | PostgreSQL 15 (SQLAlchemy ORM) |
| **Vector Store** | ChromaDB (HTTP Client / Standalone Server) |
| **Task Queue & Broker** | Celery 5 + Redis 7 |
| **RAG & Orchestration** | LangChain, Rank-BM25, Sentence-Transformers |
| **Document Parsers** | PyPDF, python-docx, Tesseract OCR (`pytesseract`, `pdf2image`) |

---

## 📁 Codebase Layout

```text
knowledge-bot/
├── api/
│   ├── admin.py            # Admin statistics, user list, access request approvals, global docs
│   ├── auth.py             # User registration, JWT login, role elevation requests
│   ├── dependencies.py     # Database session & RBAC dependency injection
│   └── main.py             # Chat sessions, query execution, document upload & delete
├── src/
│   ├── generation/
│   │   └── llm_chain.py    # Prompt templates, citation extraction, token streaming
│   ├── ingestion/
│   │   ├── chunker.py      # Recursive character text splitting
│   │   └── document_loader.py # Multi-format parsers (PDF, DOCX, TXT, CSV) with OCR fallback
│   ├── retrieval/
│   │   ├── retriever.py    # Facade: query expansion, RRF hybrid search, CrossEncoder, MMR
│   │   ├── router.py       # Query intent router (detects tabular vs textual intent)
│   │   ├── summarizer.py   # Document executive summary generator
│   │   ├── tabular_agent.py# Pandas DataFrame query execution agent
│   │   └── vector_store.py # ChromaDB client interface (HTTP & persistent)
│   ├── config.py           # Centralized environment settings & startup validator
│   ├── database.py         # SQLAlchemy engine & session maker
│   ├── llm_factory.py      # Dynamic LLM provider factory (OpenAI, Mistral, Groq)
│   ├── logger.py           # Structured logging configuration
│   ├── models.py           # Database schemas: User, ChatSession, ChatMessage, AccessRequest
│   └── worker.py           # Celery application & document processing worker task
└── tests/
    ├── test_api.py         # API endpoint test suite
    ├── test_chunker.py     # Chunking correctness tests
    ├── test_document_loader.py # Multi-format loader tests
    └── test_rag_evaluation.py  # RAG quality evaluation (Faithfulness, Relevancy, Precision, Recall)
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

# LLM Provider Configuration ("openai", "mistral", or "groq")
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...

# For Mistral:
# LLM_PROVIDER=mistral
# MISTRAL_API_KEY=...

# For Groq:
# LLM_PROVIDER=groq
# GROQ_API_KEY=...

# Security & Limits
SECRET_KEY=your_jwt_secret_key_here
MAX_FILE_SIZE_MB=50
MAX_QUERY_LENGTH=2000
```

---

## 🧪 Testing & Evaluation

Run unit and integration tests:
```bash
pytest tests/ -v
```

Run quantitative RAG quality evaluation:
```bash
python tests/test_rag_evaluation.py
```
This tests Faithfulness, Answer Relevancy, Context Precision, and Context Recall against curated enterprise test cases.