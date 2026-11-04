"""
telemetry.py — RAG Pipeline Observability, LLM Tracing & Token Accounting.

Provides unified tracing for RAG query condensation, hybrid retrieval,
reranking/MMR, and LLM streaming generation.
Supports Langfuse (v2.x) with automatic fallback to local high-precision
in-memory / log-based tracing when credentials are not configured.
"""

import time
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

from src.config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token Counting & Cost Estimation Utilities
# ---------------------------------------------------------------------------
_ENCODER = None

def get_token_encoder(model_name: str = "gpt-4o-mini"):
    """Lazy-load tiktoken encoder with fallback."""
    global _ENCODER
    if _ENCODER is None:
        try:
            import tiktoken
            try:
                _ENCODER = tiktoken.encoding_for_model(model_name)
            except Exception:
                _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.debug(f"tiktoken unavailable ({e}), using heuristic estimation.")
            _ENCODER = False
    return _ENCODER


def count_tokens(text: str, model_name: str = "gpt-4o-mini") -> int:
    """
    Count tokens for a given text string.
    Uses tiktoken cl100k_base with graceful 4 chars/token heuristic fallback.
    """
    if not text:
        return 0
    encoder = get_token_encoder(model_name)
    if encoder:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass
    # Standard rule of thumb: ~4 characters per token in English
    return max(1, len(text) // 4)


def estimate_token_cost(prompt_tokens: int, completion_tokens: int, model_name: str = "gpt-4o-mini") -> float:
    """
    Estimate USD cost for prompt and completion tokens across providers.
    Pricing per 1M tokens (Nov 2026 baseline):
      - gpt-4o-mini: $0.15 input / $0.60 output
      - mistral-small: $0.20 input / $0.60 output
      - groq/gpt-oss-120b: $0.05 input / $0.08 output
    """
    m = model_name.lower()
    if "mistral" in m:
        input_rate = 0.20 / 1_000_000
        output_rate = 0.60 / 1_000_000
    elif "groq" in m or "oss" in m:
        input_rate = 0.05 / 1_000_000
        output_rate = 0.08 / 1_000_000
    else:  # default gpt-4o-mini / openai
        input_rate = 0.15 / 1_000_000
        output_rate = 0.60 / 1_000_000

    return round((prompt_tokens * input_rate) + (completion_tokens * output_rate), 6)


# ---------------------------------------------------------------------------
# Langfuse Client Initialization
# ---------------------------------------------------------------------------
_LANGFUSE_CLIENT = None
_LANGFUSE_INITIALIZED = False

def get_langfuse_client():
    """
    Returns initialized Langfuse client if API keys are configured,
    or None if disabled / failed.
    """
    global _LANGFUSE_CLIENT, _LANGFUSE_INITIALIZED
    if _LANGFUSE_INITIALIZED:
        return _LANGFUSE_CLIENT

    _LANGFUSE_INITIALIZED = True
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        logger.info("Langfuse telemetry disabled (LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set).")
        _LANGFUSE_CLIENT = None
        return None

    try:
        from langfuse import Langfuse
        client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        logger.info(f"Langfuse telemetry client initialized for host: {LANGFUSE_HOST}")
        _LANGFUSE_CLIENT = client
        return _LANGFUSE_CLIENT
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse telemetry client: {e}. Falling back to local logging.")
        _LANGFUSE_CLIENT = None
        return None


# ---------------------------------------------------------------------------
# Tracing Abstractions (Local + Langfuse)
# ---------------------------------------------------------------------------
class TelemetrySpan:
    """Represents a measured span inside a RAG trace."""

    def __init__(self, name: str, trace_id: str, langfuse_span=None, metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.trace_id = trace_id
        self.langfuse_span = langfuse_span
        self.metadata = metadata or {}
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None
        self.duration_ms: float = 0.0
        self.input: Any = None
        self.output: Any = None
        self.status: str = "RUNNING"

    def end(self, output: Any = None, metadata: Optional[Dict[str, Any]] = None, level: str = "DEFAULT"):
        """End the span and record execution metrics."""
        self.end_time = time.perf_counter()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = "SUCCESS" if level != "ERROR" else "ERROR"
        if output is not None:
            self.output = output
        if metadata:
            self.metadata.update(metadata)

        if self.langfuse_span:
            try:
                self.langfuse_span.end(
                    output=self.output,
                    metadata=self.metadata,
                    level=level,
                )
            except Exception as e:
                logger.debug(f"Langfuse span.end() notice: {e}")

        logger.debug(f"[TelemetrySpan] '{self.name}' ({self.trace_id}) completed in {self.duration_ms:.2f}ms | status: {self.status}")
        return self


class RAGTrace:
    """
    Root trace for a single RAG request.
    Encapsulates spans: query_condense, hybrid_retrieval, rerank_mmr, llm_stream.
    """

    def __init__(
        self,
        name: str = "rag_query",
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[list] = None,
    ):
        self.name = name
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self.metadata = metadata or {}
        self.tags = tags or []
        self.start_time = time.perf_counter()
        self.spans: Dict[str, TelemetrySpan] = {}
        self.langfuse_trace = None

        if tenant_id:
            self.tags.append(f"tenant:{tenant_id}")
            self.metadata["tenant_id"] = tenant_id
        if user_id:
            self.metadata["user_id"] = user_id
        if session_id:
            self.metadata["session_id"] = session_id

        client = get_langfuse_client()
        if client:
            try:
                self.langfuse_trace = client.trace(
                    name=self.name,
                    user_id=str(user_id) if user_id else None,
                    session_id=str(session_id) if session_id else None,
                    metadata=self.metadata,
                    tags=self.tags,
                )
            except Exception as e:
                logger.debug(f"Langfuse trace creation notice: {e}")
                self.langfuse_trace = None

    @contextmanager
    def span(self, name: str, input_data: Any = None, metadata: Optional[Dict[str, Any]] = None):
        """Context manager for nested spans with automatic duration calculation."""
        lf_span = None
        if self.langfuse_trace:
            try:
                lf_span = self.langfuse_trace.span(
                    name=name,
                    input=input_data,
                    metadata=metadata,
                )
            except Exception as e:
                logger.debug(f"Langfuse span creation notice: {e}")

        s = TelemetrySpan(
            name=name,
            trace_id=f"tenant-{self.tenant_id or 'none'}",
            langfuse_span=lf_span,
            metadata=metadata,
        )
        s.input = input_data
        self.spans[name] = s
        try:
            yield s
        except Exception as exc:
            s.end(output=str(exc), metadata={"error": str(exc)}, level="ERROR")
            raise
        else:
            if s.end_time is None:
                s.end()

    def record_generation(
        self,
        name: str,
        model: str,
        prompt: Any,
        completion: Any,
        usage: Optional[Dict[str, int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record an LLM generation event in Langfuse if available."""
        if self.langfuse_trace:
            try:
                self.langfuse_trace.generation(
                    name=name,
                    model=model,
                    input=prompt,
                    output=completion,
                    usage=usage,
                    metadata=metadata,
                )
            except Exception as e:
                logger.debug(f"Langfuse record_generation notice: {e}")

    def end(self, output: Any = None, metadata: Optional[Dict[str, Any]] = None):
        """Flush trace and finalize metrics."""
        total_duration_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
        if self.langfuse_trace:
            try:
                update_params = {"metadata": {**self.metadata, **(metadata or {}), "total_duration_ms": total_duration_ms}}
                if output is not None:
                    update_params["output"] = output
                self.langfuse_trace.update(**update_params)
                client = get_langfuse_client()
                if client:
                    client.flush()
            except Exception as e:
                logger.debug(f"Langfuse flush notice: {e}")

        logger.info(
            f"[RAGTrace] '{self.name}' finished in {total_duration_ms:.2f}ms | "
            f"Tenant: {self.tenant_id} | Spans: {list(self.spans.keys())}"
        )
        return total_duration_ms


def create_rag_trace(
    name: str = "rag_query",
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list] = None,
) -> RAGTrace:
    """Factory function for creating RAG traces."""
    return RAGTrace(
        name=name,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
        tags=tags,
    )

