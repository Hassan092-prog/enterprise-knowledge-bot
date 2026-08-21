# Enterprise RAG Knowledge Bot

A production-grade, multi-tenant RAG (Retrieval-Augmented Generation) system that allows users to upload enterprise documents (PDFs, DOCX, TXT, CSV) and ask natural language questions. The AI returns precise, cited answers grounded in the uploaded documents.

Built as a highly scalable, secure, and isolated knowledge base for Enterprise environments.

---

## 🎯 What this Project Is About (The Use Case)

In a typical enterprise, employees need access to massive amounts of documentation (HR policies, technical manuals, onboarding guides). They also need to query their own private, confidential documents without exposing them to other employees. 

Standard ChatGPT cannot do this securely, nor does it have access to company-specific data.

**This project solves this by providing:**
1. **Private Sandboxes:** Every user gets their own private workspace. Documents they upload are securely isolated and cannot be queried by anyone else.
2. **Global Knowledge Base (Admin Managed):** Administrators have a dedicated dashboard to upload "Global Documents" (e.g., Company Handbooks). When a user asks a question, the AI securely queries *both* their personal documents and the global documents simultaneously.
3. **Cited Answers:** Hallucinations are mitigated because every answer includes precise citations linking back to the source document chunk.

## 🚀 Key Features & What We Implemented

- **Multi-Tenant Architecture:** Secure user authentication (JWT + bcrypt). User data is completely isolated at the Vector Database level.
- **Role-Based Access Control (RBAC):** Admin vs Regular User roles. Admins manage global resources via a dedicated dashboard.
- **PostgreSQL Migration:** Scaled up from a local SQLite file to a robust PostgreSQL relational database to handle users, credentials, and chat histories across concurrent sessions.
- **Markdown Streaming UI:** Beautiful, dark-mode native Next.js frontend. The LLM's response streams in real-time, instantly rendering Markdown (tables, code blocks, bold text) as it arrives.
- **Multi-Format Ingestion:** Upload PDFs, DOCX, TXT, and CSVs. Automatically handles parsing, chunking, and embedding.
- **Hybrid Search Architecture:** Uses ChromaDB for dense vector embeddings and BM25 for sparse keyword search.

## 🏗️ System Architecture

```text
User/Admin Upload → Parser → Chunker → Embedder → ChromaDB (Tagged with user_id or is_global)
                                                               ↓
User Query → Auth Check → Query Embedding → Semantic Search (Filtered by Identity)
                                                               ↓
                                      Context + Prompt → LLM (Mistral/OpenAI) → Streaming UI
```

## 🛠️ Tech Stack

| Component | Technology | Why |
|---|---|---|
| Frontend | Next.js 15, React 19, TailwindCSS | Modern, responsive UI with Markdown streaming |
| Backend API | FastAPI | High-performance async Python web framework |
| Database | PostgreSQL (SQLAlchemy) | Robust, relational data storage |
| Vector DB | ChromaDB | Fast similarity search with metadata filtering |
| LLM | Mistral / GPT-4o-mini | Answer generation |
| Containerization | Docker & Docker Compose | Easy, reproducible deployment |

## 📦 Setup & Deployment

The easiest way to run the application is using Docker Compose.

**1. Clone the repository**
```bash
git clone https://github.com/yourusername/enterprise-knowledge-bot.git
cd enterprise-knowledge-bot
```

**2. Set up environment variables**
```bash
cp knowledge-bot/.env.example knowledge-bot/.env
# Edit knowledge-bot/.env and add your MISTRAL_API_KEY or OPENAI_API_KEY
```

**3. Run the application**
```bash
docker compose up --build -d
```
This spins up three containers:
- `db`: PostgreSQL Database on port `5433`
- `backend`: FastAPI Python server on port `8000`
- `frontend`: Next.js Web App on port `3000`

**4. Access the App**
Open your browser and navigate to `http://localhost:3000`.

**5. Become an Admin (First Time Setup)**
Once you register your first account, promote yourself to Admin by visiting:
`http://localhost:8000/admin/make_me_admin`
Refresh the frontend, and you will see the **Admin** button to manage global documents!

## 📁 Project Structure

```text
.
├── docker-compose.yml       # Orchestrates frontend, backend, and postgres containers
├── frontend/                # Next.js web application
│   ├── app/                 # Next.js App Router (Login, Admin, Chat)
│   ├── package.json
│   └── Dockerfile
├── knowledge-bot/           # FastAPI backend & RAG logic
│   ├── api/                 # Endpoints (auth.py, admin.py, main.py)
│   ├── src/                 # RAG pipeline logic (vector_store.py, retriever.py)
│   ├── data/                # ChromaDB index (gitignored)
│   ├── db_data/             # PostgreSQL persistent volume (gitignored)
│   ├── Dockerfile           # Backend container setup
│   └── requirements.txt     
└── README.md
```

## 👨‍💻 Author

Built by [Your Name] — B.E. AIML, MJCET Hyderabad  
GitHub: [your-github-profile]  
LinkedIn: [your-linkedin]
