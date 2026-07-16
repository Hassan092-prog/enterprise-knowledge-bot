"""
app.py — Streamlit web interface for the Enterprise Knowledge Bot.

ENTRY POINT:
    Run with: streamlit run app.py

WHAT THIS FILE DOES:
    Ties together all backend phases into a working web application.
    Users upload documents, ask questions, and receive cited answers
    in real time — all through a clean browser interface.

STREAMLIT EXECUTION MODEL:
    Every user interaction causes the ENTIRE script to rerun.
    Local variables are lost on every rerun. Persistence requires:
      - st.session_state   : per-session dictionary (survives reruns)
      - @st.cache_resource : module-level singleton (survives reruns)

HOW THIS UI CONNECTS TO THE BACKEND:
    Upload   → retriever.ingest_file()       [Phase 4 Facade]
    Query    → retriever.retrieve()          [Phase 4 Retrieval]
             → stream_answer()               [Phase 5 Generation]
             → st.write_stream()             [Streamlit streaming]
    Sidebar  → retriever.list_sources()      [Phase 4 Management]
             → retriever.delete_document()
"""

from pathlib import Path

import streamlit as st

from src.config import (
    MAX_FILE_SIZE_MB,
    MAX_QUERY_LENGTH,
    SUPPORTED_EXTENSIONS,
    UPLOAD_DIR,
    validate_config,
)
from src.generation.llm_chain import _extract_sources, stream_answer
from src.logger import get_logger
from src.retrieval.retriever import Retriever

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Page config — MUST be the very first Streamlit call
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Knowledge Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------
try:
    validate_config()
except EnvironmentError as e:
    st.error(f"⚠️ Configuration Error\n\n{e}")
    st.info("Add your API key to the `.env` file and restart the app.")
    st.stop()


# ---------------------------------------------------------------------------
# Helper functions — defined before use
# ---------------------------------------------------------------------------

def _render_citations(sources: list) -> None:
    """Render a collapsible citation block below an answer."""
    if not sources:
        return
    with st.expander(f"📎 {len(sources)} source(s) cited", expanded=False):
        for filename, page in sources:
            st.markdown(f"- **{filename}** — Page {page}")


def _validate_upload(uploaded_file) -> tuple[bool, str]:
    """
    Validate an uploaded file before processing.

    Checks:
      1. File size within MAX_FILE_SIZE_MB limit
      2. Extension is supported (belt-and-suspenders — uploader also checks)

    Returns:
        (is_valid: bool, error_message: str)
    """
    # Size check
    size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return False, (
            f"File too large ({size_mb:.1f} MB). "
            f"Maximum allowed: {MAX_FILE_SIZE_MB} MB."
        )

    # Extension check
    ext = Path(uploaded_file.name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return False, (
            f"Unsupported file type: '{ext}'. "
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    return True, ""


def _validate_query(query: str) -> tuple[bool, str]:
    """
    Validate a user query before processing.

    Checks:
      1. Not empty or whitespace-only
      2. Within MAX_QUERY_LENGTH character limit

    Returns:
        (is_valid: bool, error_message: str)
    """
    if not query.strip():
        return False, "Query cannot be empty."

    if len(query) > MAX_QUERY_LENGTH:
        return False, (
            f"Query too long ({len(query)} characters). "
            f"Maximum allowed: {MAX_QUERY_LENGTH} characters."
        )

    return True, ""


# ---------------------------------------------------------------------------
# Singleton Retriever — created ONCE for the app lifetime
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading knowledge base...")
def get_retriever() -> Retriever:
    """Return the singleton Retriever — opens ChromaDB once."""
    return Retriever()


retriever = get_retriever()


# ---------------------------------------------------------------------------
# Session state — persists across reruns within one browser session
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------------------------------------------------------------------------
# SIDEBAR — knowledge base management
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("📚 Knowledge Base")
    st.markdown("---")

    # ── Upload ────────────────────────────────────────────────────────
    st.subheader("Upload Documents")
    allowed_types = [ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS]

    uploaded_files = st.file_uploader(
        label="Drag and drop files here",
        type=allowed_types,
        accept_multiple_files=True,
        help=(
            f"Supported: {', '.join(SUPPORTED_EXTENSIONS)} "
            f"· Max size: {MAX_FILE_SIZE_MB} MB per file"
        ),
    )

    if uploaded_files:
        for uploaded_file in uploaded_files:

            # Skip already-indexed files
            if uploaded_file.name in retriever.list_sources():
                st.info(f"✓ Already indexed: **{uploaded_file.name}**")
                continue

            # Validate before processing
            is_valid, error_msg = _validate_upload(uploaded_file)
            if not is_valid:
                st.error(f"❌ **{uploaded_file.name}**: {error_msg}")
                continue

            with st.spinner(f"Processing {uploaded_file.name}..."):
                try:
                    # Save with real filename so ChromaDB stores it correctly
                    save_path = UPLOAD_DIR / uploaded_file.name
                    save_path.write_bytes(uploaded_file.getvalue())

                    result = retriever.ingest_file(save_path)

                    if result.chunks_added > 0:
                        st.success(
                            f"✅ **{uploaded_file.name}** — "
                            f"{result.chunks_added} chunks indexed"
                        )
                        logger.info(
                            "Indexed '%s': %d chunks",
                            uploaded_file.name, result.chunks_added
                        )
                    else:
                        st.warning(
                            f"⚠️ **{uploaded_file.name}** — "
                            f"already fully indexed (0 new chunks)"
                        )

                except FileNotFoundError as e:
                    st.error(f"❌ File not found: {e}")
                    logger.error("FileNotFoundError for %s: %s", uploaded_file.name, e)

                except ValueError as e:
                    st.error(f"❌ Invalid file: {e}")
                    logger.error("ValueError for %s: %s", uploaded_file.name, e)

                except Exception as e:
                    st.error(
                        f"❌ Failed to process **{uploaded_file.name}**. "
                        f"Please try again or check the logs."
                    )
                    logger.error(
                        "Unexpected error ingesting %s: %s",
                        uploaded_file.name, e, exc_info=True
                    )

    st.markdown("---")

    # ── Indexed documents ─────────────────────────────────────────────
    st.subheader("Indexed Documents")
    sources = retriever.list_sources()
    stats   = retriever.get_knowledge_base_stats()

    if not sources:
        st.caption("No documents indexed yet.")
    else:
        st.caption(
            f"{stats['total_sources']} document(s) · "
            f"{stats['total_chunks']} chunks"
        )
        for source in sources:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"📄 `{source}`")
            with col2:
                if st.button("🗑️", key=f"del_{source}", help=f"Remove {source}"):
                    try:
                        deleted = retriever.delete_document(source)
                        st.success(f"Removed {source} ({deleted} chunks)")
                        logger.info("Deleted document '%s'", source)
                    except Exception as e:
                        st.error(f"Failed to delete {source}: {e}")
                    st.rerun()

    st.markdown("---")
    st.caption("Enterprise Knowledge Bot · RAG System")
    st.caption("Powered by LangChain · ChromaDB · Mistral")


# ---------------------------------------------------------------------------
# MAIN AREA
# ---------------------------------------------------------------------------

st.title("🤖 Enterprise Knowledge Bot")
st.caption(
    "Ask questions about your uploaded documents. "
    "All answers are grounded in your documents and include source citations."
)

# ── Status bar ────────────────────────────────────────────────────────────
if retriever.is_ready():
    stats = retriever.get_knowledge_base_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("Documents indexed", stats["total_sources"])
    col2.metric("Total chunks",      stats["total_chunks"])
    col3.metric("LLM model",         "mistral-small-latest")
else:
    st.info(
        "👈 Upload documents using the sidebar to get started. "
        "Supported formats: PDF, DOCX, TXT, CSV."
    )

st.markdown("---")

# ── Chat history ──────────────────────────────────────────────────────────
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("sources"):
            _render_citations(message["sources"])


# ── Chat input ────────────────────────────────────────────────────────────
if prompt := st.chat_input(
    placeholder="Ask a question about your documents...",
    disabled=not retriever.is_ready(),
):
    # Validate query before doing anything
    is_valid, error_msg = _validate_query(prompt)
    if not is_valid:
        st.warning(f"⚠️ {error_msg}")
        st.stop()

    # 1. Show user message
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({
        "role": "user", "content": prompt, "sources": None
    })

    # 2. Retrieve relevant chunks
    try:
        with st.spinner("Searching knowledge base..."):
            chunks = retriever.retrieve(prompt)
    except Exception as e:
        st.error("⚠️ Retrieval failed. Please try again.")
        logger.error("Retrieval error for query '%s': %s", prompt[:60], e, exc_info=True)
        st.stop()

    # 3. Handle no-results case
    if not chunks:
        with st.chat_message("assistant"):
            no_docs_msg = (
                "I couldn't find relevant information in the knowledge base "
                "for your question. Try uploading more documents or "
                "rephrasing your question."
            )
            st.markdown(no_docs_msg)
        st.session_state.messages.append({
            "role": "assistant", "content": no_docs_msg, "sources": []
        })
        st.stop()

    # 4. Stream the LLM response
    try:
        with st.chat_message("assistant"):
            full_response = st.write_stream(stream_answer(prompt, chunks))
            sources = _extract_sources(chunks)
            _render_citations(sources)

    except Exception as e:
        st.error(
            "⚠️ Answer generation failed. "
            "This may be a temporary API issue — please try again."
        )
        logger.error(
            "Generation error for query '%s': %s", prompt[:60], e, exc_info=True
        )
        st.stop()

    # 5. Persist to session state
    st.session_state.messages.append({
        "role":    "assistant",
        "content": full_response,
        "sources": sources,
    })

    logger.info(
        "Query answered — '%s' → %d chunks → %d sources cited",
        prompt[:60], len(chunks), len(sources),
    )