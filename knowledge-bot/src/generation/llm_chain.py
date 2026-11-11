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
import re

# Simple in-memory cache: 1000 items, 4-hour TTL (M-1 fix: reduced from 24h to limit stale deleted-doc answers)
_semantic_cache = TTLCache(maxsize=1000, ttl=14400)

def _get_cache_key(query: str, chunks: List[Document], chat_history: Optional[List[dict]] = None) -> str:
    """Generate a deterministic hash for the cache key partitioned strictly by tenant, history, and chunk IDs."""
    tenant_ids = {str(c.metadata.get("tenant_id", "0")) for c in chunks}
    tenant_str = ",".join(sorted(tenant_ids))
    chunk_summary = "|".join([
        f"{c.metadata.get('tenant_id', '')}:{c.metadata.get('source', '')}:{c.metadata.get('page', '')}:{c.metadata.get('chunk_id', '')}"
        for c in chunks
    ])
    history_str = "|".join([f"{m.get('role', '')}:{m.get('content', '')}" for m in (chat_history or [])])
    combined = f"tenant={tenant_str}::query={query.lower().strip()}::hist={history_str}::chunks={chunk_summary}"
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

Your role is to answer questions accurately and concisely using the provided document context, which includes corporate reports, technical product manuals, hardware specifications, and emergency operating protocols. Questions regarding model numbers, emergency override codes, safety procedures, or device specifications must be answered directly from the text excerpts provided.

STRICT RULES YOU MUST FOLLOW:
1. Answer using information from the document context sections provided below. You may use the conversation context to resolve references, follow-ups, and pronouns (such as "it", "they", "that total", "that division"). When answering questions about enterprise metrics, projections, or targets, associate them with the primary organization indicated in the context.
2. Do NOT use your training knowledge to invent facts not present in the context.
3. If the answer cannot be found in the provided documents, respond with:
   "I could not find sufficient information in the provided documents to answer this question."
4. For every factual claim in your answer, add a citation in this exact format:
   [Source: filename, Page X]
5. If multiple sources support a claim, cite all of them.
6. Be concise — answer the question directly without unnecessary preamble.

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

_CONDENSE_PROMPT = """You are an expert query reformulation assistant for an enterprise knowledge retrieval system.
Given the recent conversation history and a user's follow-up question, rewrite the follow-up question to be a standalone, self-contained search query.

CRITICAL RULES:
1. Preserve the primary enterprise/company name (e.g., Acme Corporation).
2. When the user asks about enterprise-wide metrics or future outlook (such as "full-year revenue", "revenue projection", "Q4 guidance", "annual growth", "operating expenses", "total revenue", "net income"), resolve pronouns like "their", "they", "the company" to the OVERALL COMPANY (e.g., Acme Corporation). Do NOT narrow company-wide metrics to an internal department (like R&D or Sales) discussed in a prior turn unless the user explicitly requested that specific department.
3. If the question explicitly asks about a specific division or product from the preceding turn (e.g., "its flagship product", "who manages it", "what did that division make"), resolve the pronoun to that specific division/product.
4. If the follow-up question is already completely self-contained, return it EXACTLY as is.
5. Do NOT answer the question. Output ONLY the standalone query.

EXAMPLES:

Conversation History:
User: What was Acme Corporation's consolidated revenue in Q3 2026?
Assistant: Acme Corporation reported $48,500,000 USD in consolidated revenue.
User: And what was its flagship product?
Assistant: The flagship product for Advanced Robotics & Automation (Project Titan) was Autonomous Roadrunner Guidance & Pursuit Systems.
Follow-up Question: How much did they spend on R&D?
Standalone Query: How much did Acme Corporation spend on Research & Development (R&D)?

Conversation History:
User: How much did they spend on R&D?
Assistant: Acme spent $9,800,000 USD on Research & Development (R&D) in Q3.
Follow-up Question: What is their full-year revenue projection?
Standalone Query: What is Acme Corporation's projected full-year 2026 revenue?

Conversation History:
User: What were Acme's key financial highlights?
Assistant: Acme reported $48.5M revenue, 64.8% gross margin, and $14.2M EBIT.
Follow-up Question: What is their guidance for next quarter?
Standalone Query: What is Acme Corporation's fiscal Q4 2026 guidance and outlook?

Conversation History:
{chat_history}

Follow-up Question: {question}
Standalone Query:"""

_INJECTION_MARKER_RE = re.compile(
    r"(?i)(SYSTEM:|ASSISTANT:|HUMAN:|###|---INST|\[INST\]|\[/INST\]|<\|im_start\|>|<\|im_end\|>)"
)


def _sanitize_history_text(text: str, max_len: int = 1000) -> str:
    """Strip common LLM prompt-injection markers and cap history message length."""
    cleaned = _INJECTION_MARKER_RE.sub("", (text or "").strip())
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned


def condense_query(query: str, chat_history: Optional[List[dict]] = None) -> str:
    """
    Reformulate ambiguous follow-up questions using recent chat context.
    If chat_history is empty or query is already standalone, returns query unchanged.
    """
    if not chat_history:
        return query

    history_lines = []
    for msg in chat_history[-4:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        text = _sanitize_history_text(msg.get("content", ""), max_len=250)
        if not text:
            continue
        history_lines.append(f"{role}: {text}")

    formatted_history = "\n".join(history_lines).strip()
    if not formatted_history:
        return query

    try:
        llm = get_llm(temperature=0.0)
        prompt = ChatPromptTemplate.from_template(_CONDENSE_PROMPT)
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({
            "chat_history": formatted_history,
            "question": query,
        }).strip()
        if result and len(result) > 2:
            logger.info("Condensed query: '%s' -> '%s'", query[:50], result[:60])
            return result
    except Exception as e:
        logger.warning("Query condensation fallback to original query: %s", e)

    return query


def extract_citation_metadata(chunks: List[Document]) -> List[dict]:
    """
    Extract structured citation metadata for the frontend Source Inspector Drawer.
    """
    seen_ids = set()
    citations = []
    for i, c in enumerate(chunks):
        chunk_id = c.metadata.get("chunk_id", f"chunk_{i+1}")
        if chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)

        source = c.metadata.get("source", "Unknown document")
        page = c.metadata.get("page", "?")
        is_global = bool(c.metadata.get("is_global", False))
        preview = c.page_content.strip()

        citations.append({
            "source": source,
            "chunk_id": chunk_id,
            "page": page,
            "content": preview,
            "is_global": is_global,
            "relevance_rank": i + 1,
        })
    return citations


def _format_history_block(chat_history: Optional[List[dict]]) -> str:
    if not chat_history:
        return ""
    lines = ["RECENT CONVERSATION CONTEXT:"]
    for msg in chat_history[-4:]:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = _sanitize_history_text(msg.get("content", ""), max_len=1000)
        if content:
            lines.append(f"{role}: {content}")
    lines.append("\n---\n")
    return "\n".join(lines)


def _build_chain(streaming: bool = False):
    """
    Build and return a LangChain LCEL chain with optional conversational history.
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("human",
         "{history_block}"
         "DOCUMENT CONTEXT:\n"
         "{context}\n\n"
         "---\n\n"
         "QUESTION: {question}\n\n"
         "Provide a precise, cited answer based only on the context above. If the question refers to prior conversation, use the context to maintain continuity."),
    ])

    llm = get_llm(streaming=streaming)
    parser = StrOutputParser()
    return prompt | llm | parser


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_answer(
    query: str,
    chunks: List[Document],
    source_filter: Optional[str] = None,
    chat_history: Optional[List[dict]] = None,
) -> Answer:
    """
    Generate a grounded, cited answer for the user's query.
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
    history_block = _format_history_block(chat_history)

    cache_key = _get_cache_key(query, chunks, chat_history=chat_history)
    if cache_key in _semantic_cache:
        logger.info("Semantic Cache HIT for query: '%s'", query[:60])
        return _semantic_cache[cache_key]

    logger.info(
        "Generating answer for query: '%s' using %d chunks (history turns: %d)",
        query[:60], len(chunks), len(chat_history) if chat_history else 0
    )

    # Build and invoke the chain
    chain = _build_chain(streaming=False)
    raw_text = chain.invoke({
        "history_block": history_block,
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
    chat_history: Optional[List[dict]] = None,
    graph_context: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Stream the LLM's answer token by token with conversational context and optional knowledge graph context.
    """
    if not chunks and not graph_context:
        yield "No relevant documents were found to answer your question."
        return

    context = build_context_block(chunks) if chunks else ""
    if graph_context:
        context = f"{graph_context}\n\n{context}" if context else graph_context

    history_block = _format_history_block(chat_history)

    logger.info(
        "Streaming answer for query: '%s' using %d chunks (history turns: %d)",
        query[:60], len(chunks), len(chat_history) if chat_history else 0
    )

    chain = _build_chain(streaming=True)

    # .stream() is the LCEL streaming method — yields tokens as they arrive
    for token in chain.stream({
        "history_block": history_block,
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