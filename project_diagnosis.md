# Enterprise Knowledge Bot: Project Diagnosis & Current State

Based on my analysis of the `knowledge-bot` repository, here is an updated view of the project's state, instructions on how to run it, and actionable recommendations for further improvement.

## 1. Quick Diagnosis & Code Review

The project is a well-structured, working RAG (Retrieval-Augmented Generation) system that has recently been upgraded to a production-ready architecture. It correctly handles the full pipeline:
- **Ingestion**: Supports multiple formats (PDF, DOCX, TXT, CSV) and now includes **OCR support via Tesseract** for scanned PDFs.
- **Retrieval**: Uses ChromaDB for vector storage and semantic search.
- **Generation**: Connects to LLMs (GPT-4 or Mistral) for answer generation with citations.
- **API & Backend**: Transitioned from Streamlit to a robust **FastAPI** backend (`api/main.py`).
- **Frontend**: A modern, scalable **Next.js** web application (`frontend/`).
- **Containerization**: Fully containerized using **Docker** and `docker-compose.yml`, orchestrating both frontend and backend seamlessly.

### Identified Weaknesses / Faults:
1. **Lack of Comprehensive Unit Tests**: There is only one evaluation script (`test_rag_evaluation.py`). There are no granular unit tests for parsing, chunking logic, and prompt generation. If you change a component, it might silently break another.
2. **Local Vector Database**: ChromaDB is running locally on disk (`data/vectorstore/`). This works well inside Docker for a single instance, but wouldn't scale horizontally if multiple users access the bot at the same time across different servers.

---

## 2. How to Run the Code

The project is now containerized, making setup significantly easier.

### Prerequisites
Make sure you have [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed on your system.

### Steps

1. **Navigate to the project directory:**
   ```bash
   cd knowledge-bot
   ```

2. **Set up Environment Variables:**
   - Copy `.env.example` to a new file named `.env` inside the `knowledge-bot` directory:
     ```bash
     cp knowledge-bot/.env.example knowledge-bot/.env
     ```
   - Open `.env` and add your LLM API keys (e.g., `OPENAI_API_KEY` or `MISTRAL_API_KEY`).

3. **Run the Application via Docker Compose:**
   ```bash
   docker-compose up --build
   ```
   This command builds and starts the FastAPI backend (with OCR support) and the Next.js frontend.

4. **Access the App:**
   - Frontend UI: `http://localhost:3000`
   - Backend API Docs (Swagger UI): `http://localhost:8000/docs`

---

## 3. Recommended Improvements & Add-Ons

With the core architectural improvements (Next.js, FastAPI, Docker, OCR) completed, here are the next steps to further enhance the enterprise readiness of this application:

> [!TIP]
> Focus on one architectural improvement at a time to ensure system stability.

### A. Feature Add-Ons
- **User Authentication & Authorization**: In an enterprise, data access needs to be restricted. Add login functionality (OAuth/JWT) and implement Role-Based Access Control (RBAC) so users only query documents they have permission to see.
- **Chat History & Persistence**: Store conversations in a database (like PostgreSQL or MongoDB) so users can resume past sessions instead of starting fresh every time.
- **Advanced RAG Techniques**: 
  - Implement **Hybrid Search** (combining Keyword search with Vector search).
  - Implement **Query Expansion** to improve retrieval accuracy.

### B. Testing & CI/CD
- **Unit Testing Suite**: Use `pytest` to write unit tests for `document_loader.py`, `chunker.py`, and `llm_chain.py`.
- **GitHub Actions (CI/CD)**: Set up a pipeline to run formatting checks (e.g., `black`, `flake8`) and your test suite automatically on every push.

### C. Scalability
- **External Vector DB**: Migrate from local ChromaDB to a managed vector database (like Pinecone, Weaviate Cloud, or an external ChromaDB cluster) to support horizontal scaling of the backend containers.
