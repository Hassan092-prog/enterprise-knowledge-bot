# System Architecture & Technical Specification

This document provides an exhaustive architectural reference for the **Enterprise Knowledge Bot**, detailing container topology, data flows, database schemas, retrieval mechanisms, and security isolation guarantees.

---

## 1. System Topology Overview

The system is deployed as a fully containerized microservices architecture coordinated via Docker Compose:

```mermaid
graph TB
    subgraph ClientLayer ["Client Layer"]
        UserBrowser["Web Browser (User / Admin)"]
    end

    subgraph FrontendApp ["Frontend Application"]
        NextJS["Next.js 15 (React 19, TailwindCSS)<br/>Port: 3000"]
    end

    subgraph BackendAPI ["API & Application Server"]
        FastAPI["FastAPI Application Server<br/>Port: 8000"]
        AuthModule["Auth & RBAC Module<br/>(JWT, Bcrypt)"]
        RouterEngine["Query Router & Tabular Agent"]
        RetrieverFacade["Retriever Engine Facade"]
    end

    subgraph AsyncWorker ["Asynchronous Processing"]
        RedisQueue["Redis 7 Queue & Broker<br/>Port: 6379"]
        CeleryWorker["Celery Worker Process<br/>(OCR, Chunking, Ingestion)"]
    end

    subgraph DataStorage ["Persistent Data Layer"]
        PostgresDB[("PostgreSQL 15 (chatdb)<br/>Port: 5433")]
        ChromaServer[("ChromaDB Standalone HTTP Server<br/>Port: 8001")]
        FileStorage[("Document Storage<br/>(data/uploads)")]
    end

    subgraph ExternalLLMs ["External Model Providers"]
        OpenAIAPI["OpenAI API (GPT-4o-mini, text-embedding-3-small)"]
        MistralAPI["Mistral API (mistral-small, mistral-embed)"]
        GroqAPI["Groq LPU (gpt-oss-120b)"]
    end

    UserBrowser -->|HTTP / SSE| NextJS
    NextJS -->|REST API / Token Streaming| FastAPI
    FastAPI --> AuthModule
    FastAPI --> RouterEngine
    FastAPI --> RetrieverFacade
    FastAPI -->|Enqueue Ingestion| RedisQueue
    RedisQueue -->|Dequeue Task| CeleryWorker
    CeleryWorker -->|Read Raw Files| FileStorage
    CeleryWorker -->|Store Vectors & Metadata| ChromaServer
    FastAPI -->|Read/Write Sessions, Users, Requests| PostgresDB
    RetrieverFacade -->|Dense Search| ChromaServer
    RetrieverFacade -->|Re-Rank & MMR| RetrieverFacade
    FastAPI -->|Streaming LLM Prompts| ExternalLLMs
    CeleryWorker -->|Generate Embeddings| ExternalLLMs
```

---

## 2. Ingestion Pipeline Architecture

Document uploads are handled asynchronously to ensure zero UI freezing or API request timeouts when ingesting massive or OCR-heavy files.

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Admin
    participant UI as Next.js Frontend
    participant API as FastAPI Backend
    participant FS as Upload File Storage
    participant Redis as Redis 7 Broker
    participant Worker as Celery Worker
    participant OCR as Tesseract / Doc Loaders
    participant Chunker as Text Chunker
    participant LLM as LLM / Embedder
    participant Chroma as ChromaDB Server

    User->>UI: Select document (.pdf, .docx, .txt, .csv) & Upload
    UI->>API: POST /upload (or /admin/upload_global) + JWT Bearer
    API->>API: Validate file extension & file size (<= 50MB)
    API->>FS: Persist uploaded bytes to data/uploads/{filename}
    API->>Redis: Enqueue process_document(file_path, user_id)
    API-->>UI: Return 200 OK {status: "processing", task_id: uuid}
    
    Note over Worker,Redis: Asynchronous Worker Execution
    Redis->>Worker: Dispatch task: process_document
    Worker->>FS: Read file
    Worker->>OCR: Parse document text (trigger OCR if scanned PDF)
    OCR-->>Worker: List[Document] pages
    Worker->>Chunker: Split into recursive chunks (1000 chars, 200 overlap)
    Chunker-->>Worker: Chunks with page & chunk_id metadata
    Worker->>LLM: Generate Executive Summary (if non-CSV)
    LLM-->>Worker: Summary text
    Worker->>Worker: Append Executive Summary Chunk
    Worker->>LLM: Compute Vector Embeddings (OpenAI / Mistral / local)
    LLM-->>Worker: Vector Embeddings (1536 or 384 dims)
    Worker->>Chroma: collection.add(ids, embeddings, metadatas, documents)
    Worker->>Worker: Log completion & update Celery state
```

---

## 3. Advanced Retrieval & Generation Pipeline

The retrieval pipeline uses a multi-stage approach combining query expansion, sparse/dense hybrid search with Reciprocal Rank Fusion, Cross-Encoder re-ranking, and Maximal Marginal Relevance.

```mermaid
flowchart TD
    Start([User Question in Chat]) --> Auth[JWT & Session Verification]
    Auth --> RouterCheck{Query Router:<br/>Is target CSV or tabular?}
    
    RouterCheck -->|Yes - CSV Detected| PandasAgent[Pandas Tabular Agent<br/>Executes DataFrame Python Analysis]
    PandasAgent --> StreamOutput([Stream Response to Frontend])
    
    RouterCheck -->|No - Textual Target| QueryExp[Query Expansion Engine<br/>LLM generates 3 synonymous search queries]
    
    QueryExp --> HybridFork[Execute Hybrid Candidate Search]
    
    subgraph CandidateRetrieval ["Candidate Retrieval Stage"]
        HybridFork --> Dense[Dense Vector Search<br/>ChromaDB HttpClient<br/>Filtered by user_id OR is_global=1]
        HybridFork --> Sparse[Sparse Keyword Search<br/>BM25Okapi]
    end
    
    Dense --> RRF[Reciprocal Rank Fusion - RRF<br/>Score = SUM 1 / 60 + rank]
    Sparse --> RRF
    
    RRF --> Candidates[Top Candidate Pool<br/>k * 4 chunks]
    
    Candidates --> CrossEncoder[Cross-Encoder Neural Re-Ranker<br/>ms-marco-MiniLM-L-6-v2<br/>Calculates true Query-Chunk cross-attention]
    
    CrossEncoder --> MMRFilter[MMR Diversity Filter<br/>Jaccard token overlap penalty<br/>Lambda = 0.3]
    
    MMRFilter --> FinalContext[Top-k Filtered Relevant Contexts]
    
    FinalContext --> PromptAssemble[Assemble System Prompt + Grounded Context + History]
    
    PromptAssemble --> LLMGeneration[LLM Streamer<br/>OpenAI / Mistral / Groq]
    
    LLMGeneration --> StreamOutput
    StreamOutput --> SaveDB[(Persist User & Assistant Messages<br/>to PostgreSQL chat_messages)]
```

---

## 4. Relational Database Schema (`PostgreSQL`)

The database is managed via SQLAlchemy ORM. The core relational entities are:

### `users` Table
Stores authenticated user accounts and assigned roles.
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | `PRIMARY KEY`, Index | Unique user identifier |
| `username` | `String` | `UNIQUE`, Index | User login name |
| `hashed_password` | `String` | Not Null | Bcrypt salted hash |
| `role` | `String` | Default: `'user'` | Role tier: `'user'`, `'editor'`, or `'admin'` |
| `created_at` | `DateTime` | Default: `utcnow` | Account creation timestamp |

### `chat_sessions` Table
Persists multi-chat conversation threads per user.
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | `PRIMARY KEY`, Index | Unique session identifier |
| `user_id` | `Integer` | `FOREIGN KEY(users.id)` | Owner user identifier |
| `title` | `String` | Default: `'New Chat'` | Conversation thread title |
| `created_at` | `DateTime` | Default: `utcnow` | Creation timestamp |

### `chat_messages` Table
Stores individual turns within a conversation thread.
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | `PRIMARY KEY`, Index | Unique message identifier |
| `session_id` | `Integer` | `FOREIGN KEY(chat_sessions.id)` | Parent conversation session |
| `role` | `String` | Not Null | Turn speaker: `'user'` or `'assistant'` |
| `content` | `Text` | Not Null | Full text or Markdown content |
| `timestamp` | `DateTime` | Default: `utcnow` | Timestamp of message |

### `access_requests` Table
Tracks user requests for elevated privilege tiers.
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `Integer` | `PRIMARY KEY`, Index | Unique request identifier |
| `user_id` | `Integer` | `FOREIGN KEY(users.id)` | Requesting user |
| `requested_role` | `String` | Not Null | Target role (`'editor'` or `'admin'`) |
| `status` | `String` | Default: `'pending'` | Status: `'pending'`, `'approved'`, `'rejected'` |
| `created_at` | `DateTime` | Default: `utcnow` | Request submission timestamp |

---

## 5. Vector Store & Multi-Tenant Metadata Scheme

All document chunks reside in ChromaDB under the `knowledge_base` collection. Complete tenant isolation is enforced at query time using ChromaDB metadata predicates.

### Metadata Schema per Chunk:
```json
{
  "source": "Q3_Financial_Review.pdf",
  "chunk_id": "Q3_Financial_Review_chunk_0012",
  "page": 4,
  "user_id": 14,
  "is_global": 0,
  "is_summary": false,
  "file_type": ".pdf"
}
```

### Retrieval Filter Logic:
When user $U_{id}$ queries the vector store:
```python
# If querying all accessible documents:
where_filter = {
    "$or": [
        {"user_id": current_user.id},
        {"is_global": 1}
    ]
}

# If user tagged a specific document with !filename:
where_filter = {
    "$and": [
        {"source": target_file},
        {
            "$or": [
                {"user_id": current_user.id},
                {"is_global": 1}
            ]
        }
    ]
}
```
This mathematically prevents any user from retrieving chunks belonging to another user, while allowing shared access to admin-approved global enterprise documents.

---

## 6. Multi-Provider LLM & Embedding Alignment

Vector compatibility is guaranteed by strictly pairing embedding models with compatible dimensionality:

| Configuration (`LLM_PROVIDER`) | Generator LLM | Embedding Model | Vector Dimension |
|---|---|---|---|
| `openai` (Default) | `gpt-4o-mini` | `text-embedding-3-small` | 1536 |
| `mistral` | `mistral-small-latest` | `mistral-embed` | 1536 |
| `groq` | `openai/gpt-oss-120b` | Local `all-MiniLM-L6-v2` | 384 |

> [!IMPORTANT]
> If `LLM_PROVIDER` is changed between providers with different vector dimensions (e.g. OpenAI $\leftrightarrow$ Groq), the ChromaDB collection must be cleared and re-indexed to prevent dimension mismatch errors.
