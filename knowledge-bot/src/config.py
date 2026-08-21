"""
config.py — Central configuration for the Enterprise Knowledge Bot.

WHY THIS FILE EXISTS:
  All settings live here. Every other module imports from here.
  If you want to change the model, chunk size, or any parameter,
  you change it in exactly ONE place, not scattered across 10 files.

INDUSTRY PATTERN:
  This is called the "Config Object" pattern. Companies like Stripe,
  Airbnb, and Google use this at scale (often with more layers like
  YAML files or cloud config services). For our project, a single
  Python file is the right level of complexity.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from .env file
# ---------------------------------------------------------------------------
# load_dotenv() reads the .env file and makes variables available via os.getenv()
# This MUST be called before any os.getenv() calls below.
# If .env doesn't exist (e.g. in CI/CD), it fails silently — which is fine
# because environment variables will already be set by the system.
load_dotenv()


# ---------------------------------------------------------------------------
# Paths — everything relative to the project root
# ---------------------------------------------------------------------------
# Path(__file__) = the path of THIS file (src/config.py)
# .parent        = src/
# .parent.parent = knowledge-bot/   <-- project root
PROJECT_ROOT = Path(__file__).parent.parent

DATA_DIR        = PROJECT_ROOT / "data"
UPLOAD_DIR      = DATA_DIR / "uploads"
VECTORSTORE_DIR = DATA_DIR / "vectorstore"
LOG_DIR         = PROJECT_ROOT / "logs"

# Ensure these directories always exist when the app starts
for _dir in [UPLOAD_DIR, VECTORSTORE_DIR, LOG_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# API Keys — NEVER hardcode these. Always read from environment.
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# We also support Mistral as a free/open-source alternative
MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")

# Which LLM provider to use: "openai" or "mistral"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")

# Production PostgreSQL Database URL (falls back to local SQLite if not set)
DATABASE_URL: str = os.getenv("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# LLM Settings
# ---------------------------------------------------------------------------
# The model that GENERATES answers (the "G" in RAG)
LLM_MODEL: str = ("mistral-small-latest" if LLM_PROVIDER == "mistral" else "gpt-4o-mini")

# Controls randomness: 0 = deterministic, 1 = creative
# For factual Q&A over documents, we want LOW temperature (0.0 - 0.2)
# Higher temperature = more creative but less accurate = BAD for enterprise RAG
LLM_TEMPERATURE: float = 0.0

# Maximum tokens the LLM can generate in its answer
LLM_MAX_TOKENS: int = 1024


# ---------------------------------------------------------------------------
# Embedding Settings
# ---------------------------------------------------------------------------
# The model that converts text → vectors (the "R" in RAG)
# CRITICAL: You must use the SAME embedding model for both:
#   1. Ingestion (converting document chunks to vectors)
#   2. Retrieval  (converting user queries to vectors)
# If you use different models, the vectors are incompatible.
EMBEDDING_MODEL: str = ("mistral-embed" if LLM_PROVIDER == "mistral" else "text-embedding-3-small")

# Embedding dimension (must match the model above)
EMBEDDING_DIMENSION: int = 1536


# ---------------------------------------------------------------------------
# Chunking Settings
# ---------------------------------------------------------------------------
# CHUNK_SIZE: How many characters per chunk.
# Too small → chunks lack context, LLM gets fragments
# Too large → chunks are expensive, retrieval is less precise
# 1000 chars ≈ 150-200 words ≈ one solid paragraph — industry sweet spot
CHUNK_SIZE: int = 1000

# CHUNK_OVERLAP: How many characters to repeat between adjacent chunks.
# WHY: Sentences at chunk boundaries get split. Overlap ensures we don't
# lose meaning at the edges. Think of it like overlapping puzzle pieces.
# 200 chars ≈ 20% overlap — standard industry default
CHUNK_OVERLAP: int = 200


# ---------------------------------------------------------------------------
# Retrieval Settings
# ---------------------------------------------------------------------------
# How many chunks to retrieve per query (top-k retrieval)
# Too few → might miss relevant info
# Too many → LLM context gets noisy, costs more
RETRIEVAL_TOP_K: int = 5

# ChromaDB collection name (like a table name in a traditional database)
CHROMA_COLLECTION_NAME: str = "knowledge_base"


# ---------------------------------------------------------------------------
# Supported file types
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS: list[str] = [".pdf", ".docx", ".txt", ".csv"]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: Path = LOG_DIR / "app.log"


# ---------------------------------------------------------------------------
# Validation — catch misconfigurations at startup, not at runtime
# ---------------------------------------------------------------------------
def validate_config() -> None:
    """
    Check that all required settings are present.
    Called once at application startup.
    
    WHY: It is much better to fail fast with a clear error message
    than to crash 10 minutes into processing with a cryptic KeyError.
    This is called "fail-fast" design — a production best practice.
    """
    errors: list[str] = []

    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        errors.append(
            "OPENAI_API_KEY is not set. Add it to your .env file."
        )

    if LLM_PROVIDER == "mistral" and not MISTRAL_API_KEY:
        errors.append(
            "MISTRAL_API_KEY is not set. Add it to your .env file."
        )

    if errors:
        raise EnvironmentError(
            "Configuration errors found:\n" + "\n".join(f"  - {e}" for e in errors)
        )


# ---------------------------------------------------------------------------
# Production hardening limits (Phase 7)
# ---------------------------------------------------------------------------
# Maximum characters allowed in a user query.
# Prevents prompt injection attacks and runaway API costs.
# 2000 chars ≈ 400 words — more than enough for any real question.
MAX_QUERY_LENGTH: int = 2000

# Maximum file size in megabytes allowed for upload.
# Prevents memory exhaustion on large uploads.
MAX_FILE_SIZE_MB: int = 50

# Maximum number of retry attempts for API calls.
MAX_RETRIES: int = 3

# Base delay in seconds for exponential backoff.
RETRY_BASE_DELAY: float = 2.0
