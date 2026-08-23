"""
llm_chain.py — LLM integration and prompt engineering for the RAG pipeline.

WHAT THIS FILE DOES:
    Takes the retrieved chunks from retriever.py and the user's question,
    constructs a carefully engineered prompt, calls the LLM, and returns
    a structured answer with source citations.

    This is the "G" in RAG — Generation.

WHY PROMPT ENGINEERING MATTERS:
    The LLM is the most capable component in the pipeline — but also
    the most dangerous if given poor instructions. Without careful
    prompting, it will:
      - Hallucinate facts not in the provided context
      - Answer from its training data instead of your documents
      - Return prose with no source citations
      - Give inconsistent output formats

    The prompt is your last line of defence against all of these.

THREE JOBS OF THE PROMPT:
    1. Hallucination prevention — "Answer ONLY from the context below"
    2. Citation forcing       — "Reference [Source: file, page] for each claim"
    3. Output structure       — define exactly what the answer should look like

LCEL (LangChain Expression Language):
    We build chains using the pipe operator |:
        chain = prompt | llm | parser
        answer = chain.invoke(inputs)
    Each component's output becomes the next component's input.
    LCEL supports streaming out of the box — tokens appear as they generate.

DATA FLOW:
    query (str) + chunks (List[Document])
        → build_context_prompt()     format chunks into numbered context
        → ChatPromptTemplate         system + human message structure
        → ChatOpenAI                 LLM API call (streaming or batch)
        → StrOutputParser            extract text from LLM response
        → Answer dataclass           structured result with citations
"""

from dataclasses import dataclass, field
from typing import Generator, List, Optional

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from src.llm_factory import get_llm
from cachetools import TTLCache
import hashlib

# Simple in-memory cache: 1000 items, 24-hour TTL
_semantic_cache = TTLCache(maxsize=1000, ttl=86400)

def _get_cache_key(query: str, chunks: List[Document]) -> str:
    """Generate a deterministic hash for the cache key."""
    chunk_summary = "|".join([c.metadata.get("source", "") + str(c.metadata.get("page", "")) for c in chunks])
    combined = f"{query.lower().strip()}::{chunk_summary}"
    return hashlib.md5(combined.encode()).hexdigest()

from src.config import (
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_PROVIDER,
)
from src.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Return type — structured answer with citations
# ---------------------------------------------------------------------------

@dataclass
class Answer:
    """
    Structured output from the LLM chain.

    WHY A DATACLASS:
        Raw strings are unworkable — the UI needs the answer text,
        the citation list, and diagnostic metadata separately.
        A dataclass gives named fields, type hints, and clean repr.

    Fields:
        text        : The LLM's answer in plain text
        sources     : Deduplicated list of (filename, page) tuples cited
        model       : Which LLM model produced this answer
        chunks_used : How many context chunks were sent to the LLM
        has_answer  : False if LLM said the context was insufficient
    """
    text:        str
    sources:     List[tuple]         = field(default_factory=list)
    model:       str                 = LLM_MODEL
    chunks_used: int                 = 0
    has_answer:  bool                = True


# ---------------------------------------------------------------------------
# System prompt — the permanent instructions that never change
# ---------------------------------------------------------------------------

# WHY A SEPARATE CONSTANT:
#   The system prompt defines the AI's entire role and constraints.
#   Keeping it as a named constant makes it easy to find, version,
#   and tune without hunting through function bodies.
#
# KEY DECISIONS IN THIS PROMPT:
#   1. "ONLY from the provided context" — hallucination prevention
#   2. "[Source: X, Page Y]" format   — machine-parseable citations
#   3. "If the answer cannot be found" — graceful insufficient-context handling
#   4. "Do not make up information"    — explicit repetition of the constraint
#      (LLMs respond better to redundant emphasis on safety constraints)

_SYSTEM_PROMPT = """You are an expert document analyst for an enterprise knowledge base system.

Your role is to answer questions accurately and concisely using ONLY the provided document context.

STRICT RULES YOU MUST FOLLOW:
1. Answer ONLY using information from the context sections provided below.
2. Do NOT use your training knowledge to supplement or fill gaps in the context.
3. If the answer cannot be found in the provided context, respond with exactly:
   "I could not find sufficient information in the provided documents to answer this question."
4. Do NOT make up, infer, or extrapolate information that is not explicitly stated.
5. For every factual claim in your answer, add a citation in this exact format:
   [Source: filename, Page X]
6. If multiple sources support a claim, cite all of them.
7. Be concise — answer the question directly without unnecessary preamble.

CITATION FORMAT EXAMPLE:
   "Revenue grew 23% year-over-year [Source: annual_report.pdf, Page 3], driven
    primarily by cloud services expansion [Source: annual_report.pdf, Page 7]."
"""

# ---------------------------------------------------------------------------
# Context block builder
# ---------------------------------------------------------------------------

def build_context_block(chunks: List[Document]) -> str:
    """
    Format retrieved chunks into a numbered context block for the prompt.

    WHY NUMBERED SECTIONS:
        Numbered sections make it easy for the LLM to reference specific
        chunks and for us to parse which chunks were actually used.
        Plain concatenation loses the boundaries between chunks.

    WHY INCLUDE METADATA IN THE BLOCK:
        The LLM needs to know the source filename and page number so it
        can write proper citations. Without this, it can only say
        "the document says..." instead of "annual_report.pdf, page 3 says..."

    Args:
        chunks: List of Documents from retriever.retrieve()

    Returns:
        Formatted string like:
            [Context 1 — annual_report.pdf, Page 3]
            Revenue grew 23% year-over-year to $4.2 billion...

            [Context 2 — risk_register.pdf, Page 1]
            Key risks include regulatory changes in...

    Example prompt injection:
        The LLM receives this block inside the human message, immediately
        before the user's question. It has full visibility into sources.
    """
    if not chunks:
        return "No context documents were retrieved."

    sections = []
    for i, chunk in enumerate(chunks, start=1):
        source = chunk.metadata.get("source", "Unknown source")
        page   = chunk.metadata.get("page", "?")
        text   = chunk.page_content.strip()

        section = f"[Context {i} — {source}, Page {page}]\n{text}"
        sections.append(section)

    return "\n\n".join(sections)


def _extract_sources(chunks: List[Document]) -> List[tuple]:
    """
    Extract unique (source, page) tuples from retrieved chunks.

    Deduplicates so the same page is not listed twice in citations.
    Sorted for deterministic output.

    Args:
        chunks: Retrieved Document objects with metadata.

    Returns:
        Sorted list of (filename, page_number) tuples.
        Example: [("annual_report.pdf", 3), ("annual_report.pdf", 7)]
    """
    seen = set()
    sources = []
    for chunk in chunks:
        source = chunk.metadata.get("source", "Unknown")
        page   = chunk.metadata.get("page", "?")
        key    = (source, page)
        if key not in seen:
            seen.add(key)
            sources.append(key)
    return sorted(sources)


# ---------------------------------------------------------------------------
# LLM chain builder
# ---------------------------------------------------------------------------

def _build_chain(streaming: bool = False):
    """
    Build and return a LangChain LCEL chain.

    LCEL CHAIN:  prompt | llm | parser
        prompt  — ChatPromptTemplate formats system + human messages
        llm     — ChatOpenAI makes the API call
        parser  — StrOutputParser extracts text from the response object

    WHY LCEL OVER MANUAL API CALLS:
        1. Streaming support is built in — just call .stream() instead of .invoke()
        2. Composable — swap the LLM or parser without changing other code
        3. Automatic retry and error handling hooks
        4. Observable — LangSmith can trace every call automatically

    Args:
        streaming: If True, configure the LLM for token streaming.

    Returns:
        A runnable LCEL chain ready for .invoke() or .stream()
    """
    # ── Prompt template ───────────────────────────────────────────────
    # ChatPromptTemplate.from_messages builds the [system, human] pair.
    # {context} and {question} are template variables filled at call time.
    # The human message puts context BEFORE the question — this is the
    # standard RAG pattern. The LLM reads the evidence first, then
    # processes the question in light of that evidence.
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("human",
         "DOCUMENT CONTEXT:\n"
         "{context}\n\n"
         "---\n\n"
         "QUESTION: {question}\n\n"
         "Provide a precise, cited answer based only on the context above."),
    ])

    # ── LLM ───────────────────────────────────────────────────────────
    # temperature=0.0 → deterministic, factual responses
    #   For creative tasks you'd set this higher (0.7-1.0).
    #   For enterprise Q&A over documents, 0.0 is always correct.
    # streaming=True  → enables token-by-token output in the UI
    llm = get_llm(streaming=streaming)

    # ── Output parser ─────────────────────────────────────────────────
    # StrOutputParser extracts .content from the AIMessage object.
    # Without it, .invoke() returns an AIMessage, not a plain string.
    parser = StrOutputParser()

    return prompt | llm | parser


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_answer(
    query: str,
    chunks: List[Document],
    source_filter: Optional[str] = None,
) -> Answer:
    """
    Generate a grounded, cited answer for the user's query.

    This is the primary function the UI calls after retrieval.
    Uses batch mode (waits for the full answer before returning).
    For streaming, use stream_answer() instead.

    Args:
        query:         The user's natural language question.
        chunks:        Retrieved context chunks from retriever.retrieve().
        source_filter: Optional — not used here, passed for logging context.

    Returns:
        Answer dataclass with text, sources, model, and chunks_used.

    Example:
        chunks = retriever.retrieve("What was the revenue growth?")
        answer = generate_answer("What was the revenue growth?", chunks)
        print(answer.text)
        print(answer.sources)
    """
    if not chunks:
        logger.warning("generate_answer() called with no chunks — LLM has no context")
        return Answer(
            text="No relevant documents were found in the knowledge base "
                 "to answer your question. Please upload relevant documents first.",
            sources=[],
            chunks_used=0,
            has_answer=False,
        )

    # Build the context block from retrieved chunks
    context = build_context_block(chunks)

    cache_key = _get_cache_key(query, chunks)
    if cache_key in _semantic_cache:
        logger.info("Semantic Cache HIT for query: '%s'", query[:60])
        return _semantic_cache[cache_key]

    logger.info(
        "Generating answer for query: '%s' using %d chunks",
        query[:60], len(chunks)
    )

    # Build and invoke the chain
    chain = _build_chain(streaming=False)
    raw_text = chain.invoke({
        "context":  context,
        "question": query,
    })

    # Detect "I could not find" responses
    no_answer_signal = "i could not find sufficient information"
    has_answer = no_answer_signal not in raw_text.lower()

    sources = _extract_sources(chunks)

    logger.info(
        "Answer generated — %d chars, %d sources, has_answer=%s",
        len(raw_text), len(sources), has_answer
    )

    answer = Answer(
        text=raw_text,
        sources=sources,
        model=LLM_MODEL,
        chunks_used=len(chunks),
        has_answer=has_answer,
    )
    
    _semantic_cache[cache_key] = answer
    return answer

def stream_answer(
    query: str,
    chunks: List[Document],
) -> Generator[str, None, None]:
    """
    Stream the LLM's answer token by token.

    Used in the Streamlit UI with st.write_stream() to show the answer
    appearing word-by-word in real time — like ChatGPT's interface.

    WHY STREAMING MATTERS FOR UX:
        Without streaming, the user waits 5-10 seconds staring at a spinner.
        With streaming, they see words appearing within ~1 second and can
        start reading while the rest generates. This dramatically improves
        perceived performance even though total generation time is the same.

    Args:
        query:  The user's natural language question.
        chunks: Retrieved context chunks from retriever.retrieve().

    Yields:
        String tokens as they arrive from the OpenAI API.

    Usage in Streamlit:
        with st.chat_message("assistant"):
            response = st.write_stream(stream_answer(query, chunks))

    Usage in plain Python:
        for token in stream_answer(query, chunks):
            print(token, end="", flush=True)
    """
    if not chunks:
        yield "No relevant documents were found to answer your question."
        return

    context = build_context_block(chunks)

    logger.info(
        "Streaming answer for query: '%s' using %d chunks",
        query[:60], len(chunks)
    )

    chain = _build_chain(streaming=True)

    # .stream() is the LCEL streaming method — yields tokens as they arrive
    for token in chain.stream({
        "context":  context,
        "question": query,
    }):
        yield token


# ---------------------------------------------------------------------------
# Retry logic with exponential backoff (Phase 7)
# ---------------------------------------------------------------------------

import time
import random as _random

from src.config import MAX_RETRIES, RETRY_BASE_DELAY


def _with_retry(fn, *args, **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff on failure.

    WHY EXPONENTIAL BACKOFF:
        API rate limits (429) and transient server errors (500/503) are
        temporary. Retrying immediately hammers the server and makes things
        worse. Waiting exponentially longer (2s, 4s, 8s) gives the service
        time to recover.

        Adding random jitter (±0-1s) prevents the "thundering herd" problem
        where many clients retry at exactly the same time after an outage.

    WHICH ERRORS TO RETRY:
        429 Too Many Requests — rate limit, always retry with backoff
        500/502/503/504       — server error, transient, safe to retry
        AuthenticationError   — permanent, never retry (wrong key)
        ValueError            — permanent, never retry (bad input)

    Args:
        fn:      The callable to retry (e.g. chain.invoke)
        *args:   Positional args for fn
        **kwargs: Keyword args for fn

    Returns:
        fn's return value on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)

        except Exception as e:
            error_str = str(e).lower()

            # Permanent errors — do not retry
            if any(term in error_str for term in [
                "authentication", "invalid api key",
                "permission", "not found", "invalid request"
            ]):
                logger.error("Permanent API error (no retry): %s", e)
                raise

            last_error = e

            if attempt < MAX_RETRIES:
                # Exponential backoff: 2s, 4s, 8s + jitter
                delay = RETRY_BASE_DELAY ** attempt + _random.uniform(0, 1)
                logger.warning(
                    "API call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt, MAX_RETRIES, e, delay
                )
                time.sleep(delay)
            else:
                logger.error(
                    "API call failed after %d attempts: %s", MAX_RETRIES, e
                )

    raise last_error


def generate_answer_safe(
    query: str,
    chunks: List[Document],
) -> Answer:
    """
    generate_answer() wrapped with retry logic.

    Drop-in replacement for generate_answer() in production.
    Retries on transient API errors with exponential backoff.

    Args:
        query:  User's natural language question.
        chunks: Retrieved context chunks.

    Returns:
        Answer dataclass — same as generate_answer().
    """
    return _with_retry(generate_answer, query, chunks)