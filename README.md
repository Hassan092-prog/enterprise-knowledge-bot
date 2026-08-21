# Multi-Format Enterprise Knowledge Bot

A production-grade RAG (Retrieval-Augmented Generation) system that allows users to upload enterprise documents (PDFs, DOCX, TXT, CSV) and ask natural language questions. The AI returns precise, cited answers grounded in the uploaded documents.

Built as part of a deep-dive AI engineering curriculum at MJCET.

---

## What It Does

- Upload multiple documents in different formats (including OCR for scanned PDFs via Tesseract)
- Ask questions in plain English
- Receive answers with exact source citations (document name + page number)
- Handles long documents that exceed LLM context windows
- Supports both OpenAI (GPT-4) and Mistral (open-source, free)
- Modern, scalable architecture with a Next.js frontend and FastAPI backend

## System Architecture

```
Documents → Parser (OCR enabled) → Chunker → Embeddings → ChromaDB
                                                              ↓
User Query → Query Embedding → Semantic Search → Re-ranker
                                                              ↓
                                     Context + Prompt → LLM → Cited Answer
```

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Frontend | Next.js / React | Modern, responsive UI |
| Backend API | FastAPI | High-performance Python web framework |
| LLM | GPT-4o-mini / Mistral | Answer generation |
| Embeddings | text-embedding-3-small | Semantic representation |
| Vector DB | ChromaDB | Fast similarity search |
| Framework | LangChain | RAG pipeline orchestration |
| Containerization | Docker & Docker Compose | Easy, reproducible deployment |
| Language | Python 3.11+ / TypeScript | Industry standards |

## Setup

The easiest way to run the application is using Docker Compose.

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/knowledge-bot.git
cd knowledge-bot
```

**2. Set up environment variables**
```bash
cp knowledge-bot/.env.example knowledge-bot/.env
# Edit knowledge-bot/.env and add your OpenAI API key
```

**3. Run the application with Docker Compose**
```bash
docker-compose up --build
```
This will start the backend on port `8000` and the frontend on port `3000`.

**4. Access the App**
Open your browser and navigate to `http://localhost:3000`.

## Project Structure

```
.
├── docker-compose.yml       # Orchestrates frontend and backend containers
├── frontend/                # Next.js web application
│   ├── app/
│   ├── public/
│   ├── package.json
│   └── Dockerfile
├── knowledge-bot/           # FastAPI backend & RAG logic
│   ├── api/                 # FastAPI endpoints
│   ├── src/                 # RAG pipeline logic (ingestion, retrieval, generation)
│   ├── data/                # Uploads & ChromaDB index (gitignored)
│   ├── tests/               # Unit tests
│   ├── Dockerfile           # Backend container setup (includes Tesseract OCR)
│   ├── requirements.txt     
│   └── .env.example         
└── README.md
```

## Key Concepts Demonstrated

- **RAG Pipeline**: Full retrieval-augmented generation from scratch
- **Chunking Strategy**: Recursive character splitting with overlap
- **Semantic Search**: Cosine similarity over dense embeddings
- **Prompt Engineering**: Context injection with citation prompting
- **Production Patterns**: Dockerization, REST APIs (FastAPI), separated Frontend (Next.js), OCR integration.

## Author

Built by [Your Name] — B.E. AIML, MJCET Hyderabad  
GitHub: [your-github-profile]  
LinkedIn: [your-linkedin]
