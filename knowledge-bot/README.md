# Knowledge Bot Backend API

The core RAG (Retrieval-Augmented Generation) engine and REST API for the Enterprise Knowledge Bot.

## Overview
This FastAPI service handles all the heavy lifting:
- **Authentication:** JWT issuance and validation.
- **Document Processing:** Loading PDFs (with OCR support), Word Docs, TXTs, and CSVs.
- **Chunking & Embedding:** Splitting documents into smaller semantic chunks and converting them into dense vectors.
- **Vector Database & Hybrid Search:** Interfacing with ChromaDB to store/retrieve vectors and utilizing BM25 for sparse keyword search.
- **LLM Integration:** Formatting retrieved context and querying Mistral or OpenAI models for the final answer.
- **Tabular Data Routing:** Directing CSV queries to a dedicated Pandas agent for aggregations and analysis.
- **Role-Based Access Control:** Ensuring users only query documents they own, or global documents managed by Admins.

## Stack
- **Framework:** FastAPI
- **Database:** PostgreSQL (via SQLAlchemy)
- **Vector Store:** ChromaDB
- **LLM Framework:** LangChain

## Key Components

### `api/`
Contains the REST endpoints:
- `auth.py`: Login and Registration endpoints.
- `admin.py`: Endpoints for managing Global Documents and viewing stats.
- `main.py`: Core endpoints for chat sessions, document uploads, and querying.
- `dependencies.py`: Dependency injection for JWT validation and RBAC.

### `src/`
Contains the business logic:
- `ingestion/`: Logic for parsing files (`document_loader.py`) and splitting text (`chunker.py`).
- `retrieval/`: Logic for storing/querying vectors (`vector_store.py`), orchestrating the RAG pipeline (`retriever.py`), routing queries (`router.py`), and analyzing CSVs (`tabular_agent.py`).
- `models.py`: SQLAlchemy database schemas.

### `tests/`
Contains the unit testing suite for the backend:
- Testing API endpoints, document loading, and chunking logic.
- RAG evaluation script (`test_rag_evaluation.py`).

## Configuration
All configuration is handled via environment variables (usually passed in by Docker Compose). See `.env.example` for details.