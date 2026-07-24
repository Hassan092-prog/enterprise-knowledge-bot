# Multi-Format Enterprise Knowledge Bot

A production-grade RAG (Retrieval-Augmented Generation) system that allows users to upload enterprise documents (PDFs, DOCX, TXT, CSV) and ask natural language questions. The AI returns precise, cited answers grounded in the uploaded documents.

Built as part of a deep-dive AI engineering curriculum at MJCET.

---

## What It Does

- Upload multiple documents in different formats
- Ask questions in plain English
- Receive answers with exact source citations (document name + page number)
- Handles long documents that exceed LLM context windows
- Supports both OpenAI (GPT-4) and Mistral (open-source, free)

## System Architecture

```
Documents → Parser → Chunker → Embeddings → ChromaDB
                                                ↓
User Query → Query Embedding → Semantic Search → Re-ranker
                                                ↓
                              Context + Prompt → LLM → Cited Answer
```

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| LLM | GPT-4o-mini / Mistral | Answer generation |
| Embeddings | text-embedding-3-small | Semantic representation |
| Vector DB | ChromaDB | Fast similarity search |
| Framework | LangChain | RAG pipeline orchestration |
| UI | Streamlit | Rapid AI prototype UI |
| Language | Python 3.11+ | Industry standard for AI |

## Setup

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/knowledge-bot.git
cd knowledge-bot
```

**2. Create a virtual environment**
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Set up environment variables**
```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

**5. Run the application**
```bash
streamlit run app.py
```

## Project Structure

```
knowledge-bot/
├── src/
│   ├── config.py            # All settings — single source of truth
│   ├── logger.py            # Structured logging
│   ├── ingestion/
│   │   ├── document_loader.py   # Parse PDF, DOCX, TXT, CSV
│   │   └── chunker.py           # Split text into overlapping chunks
│   ├── retrieval/
│   │   ├── vector_store.py      # ChromaDB interface
│   │   └── retriever.py         # Semantic search + re-ranking
│   └── generation/
│       └── llm_chain.py         # Prompt engineering + LLM call
├── data/
│   ├── uploads/             # Uploaded documents (gitignored)
│   └── vectorstore/         # ChromaDB index (gitignored)
├── logs/                    # Application logs (gitignored)
├── tests/                   # Unit tests
├── app.py                   # Streamlit entry point
├── .env.example             # Environment variable template
├── requirements.txt         # Pinned dependencies
└── README.md
```

## Key Concepts Demonstrated

- **RAG Pipeline**: Full retrieval-augmented generation from scratch
- **Chunking Strategy**: Recursive character splitting with overlap
- **Semantic Search**: Cosine similarity over dense embeddings
- **Prompt Engineering**: Context injection with citation prompting
- **Production Patterns**: Logging, error handling, config management, type hints

## Author

Built by [Your Name] — B.E. AIML, MJCET Hyderabad  
GitHub: [your-github-profile]  
LinkedIn: [your-linkedin]
