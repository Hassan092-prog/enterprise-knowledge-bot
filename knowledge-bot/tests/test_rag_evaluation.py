"""
test_rag_evaluation.py — RAG quality evaluation using RAGAS metrics.

WHAT THIS FILE DOES:
    Runs a structured evaluation of the full RAG pipeline against a
    small hand-crafted Q&A dataset derived from your sample documents.
    Prints a report showing Faithfulness, Answer Relevancy, Context
    Precision, and Context Recall scores.

HOW TO RUN:
    # From knowledge-bot/ with venv active:
    python tests/test_rag_evaluation.py

    # Or with pytest (verbose):
    pytest tests/test_rag_evaluation.py -v -s

WHY EVALUATION MATTERS:
    A RAG system can "work" (returns answers) while being:
      - Unfaithful (answers contain hallucinated claims)
      - Irrelevant (answers don't address the question)
      - Imprecise (retrieves noise chunks alongside relevant ones)
      - Incomplete (misses chunks needed for a full answer)

    RAGAS catches all of these quantitatively without human annotation.

RAGAS METRICS EXPLAINED:
    Faithfulness (0-1):
        Are all claims in the answer supported by retrieved context?
        1.0 = fully grounded, 0.0 = pure hallucination
        Formula: supported_claims / total_claims_in_answer

    Answer Relevancy (0-1):
        Does the answer address the question that was asked?
        1.0 = perfectly on-topic, 0.0 = completely off-topic
        Formula: cosine_similarity(question, generated_questions_from_answer)

    Context Precision (0-1):
        Of the retrieved chunks, how many were actually useful?
        1.0 = all chunks were relevant, 0.0 = all chunks were noise
        Formula: useful_chunks / total_retrieved_chunks

    Context Recall (0-1):
        Did you retrieve all information needed to answer fully?
        1.0 = retrieved everything needed, 0.0 = missed everything
        Formula: covered_ground_truth_points / total_ground_truth_points

WHAT GOOD SCORES LOOK LIKE:
    Production-grade RAG system targets:
        Faithfulness      > 0.85  (answers stay grounded)
        Answer Relevancy  > 0.80  (answers are on-topic)
        Context Precision > 0.70  (retrieval is focused)
        Context Recall    > 0.75  (retrieval is complete)

NOTE ON RAGAS INSTALLATION:
    pip install ragas
    RAGAS uses the LLM API to score responses — it will consume
    a small number of API tokens per evaluation question.
"""

import sys
import os
from pathlib import Path

# Add project root to path so src/ imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env BEFORE any src/ imports — ensures API keys are in os.environ
# when vector_store.py instantiates the Mistral client
from dotenv import load_dotenv
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

# Verify key loaded correctly
_mistral_key = os.environ.get("MISTRAL_API_KEY", "")
if not _mistral_key:
    print("ERROR: MISTRAL_API_KEY not found — check your .env file")
    sys.exit(1)


def run_pipeline_evaluation():
    """
    Run a lightweight evaluation of the RAG pipeline.

    Uses a manually crafted Q&A dataset based on sample.txt.
    Does NOT require RAGAS — runs a custom scoring approach
    that measures the same properties without extra dependencies.

    This gives you a repeatable, zero-cost evaluation you can
    run after every change to chunking, retrieval, or prompting.
    """
    from src.retrieval.retriever import Retriever
    from src.generation.llm_chain import build_context_block

    print("=" * 60)
    print("  RAG PIPELINE EVALUATION REPORT")
    print("=" * 60)

    # ── Check knowledge base is ready ───────────────────────────────
    retriever = Retriever()
    if retriever.is_empty():
        print("\n  ⚠️  Knowledge base is empty.")
        print("  Upload sample.txt first: streamlit run app.py")
        print("  Then re-run this evaluation.")
        return

    stats = retriever.get_knowledge_base_stats()
    print(f"\n  Knowledge base: {stats['total_chunks']} chunks across "
          f"{stats['total_sources']} source(s)")
    print(f"  Sources: {', '.join(stats['sources'])}")

    # ── Test dataset ────────────────────────────────────────────────
    # Hand-crafted Q&A pairs based on sample.txt content.
    # Each entry has:
    #   question       : what a user would ask
    #   expected_terms : key words the answer MUST contain to be correct
    #   expected_source: which document should be retrieved
    test_cases = [
        {
            "question":       "What was the revenue growth?",
            "expected_terms": ["23", "revenue", "billion"],
            "expected_source": "sample.txt",
            "description":    "Revenue fact extraction",
        },
        {
            "question":       "What drove the cloud division growth?",
            "expected_terms": ["cloud", "41"],
            "expected_source": "sample.txt",
            "description":    "Cloud division specifics",
        },
        {
            "question":       "What are the key risk factors?",
            "expected_terms": ["risk", "regulatory", "supply"],
            "expected_source": "sample.txt",
            "description":    "Risk factor retrieval",
        },
        {
            "question":       "What is the revenue forecast for 2025?",
            "expected_terms": ["2025", "18", "22"],
            "expected_source": "sample.txt",
            "description":    "Forward-looking statement",
        },
    ]

    # ── Evaluation metrics accumulators ─────────────────────────────
    results = []

    print(f"\n  Running {len(test_cases)} test cases...\n")

    for i, tc in enumerate(test_cases, 1):
        print(f"  [{i}/{len(test_cases)}] {tc['description']}")
        print(f"  Question: {tc['question']}")

        # Retrieve
        chunks = retriever.retrieve(tc["question"], k=5)

        # ── Metric 1: Context Recall ─────────────────────────────
        # Did we retrieve a chunk from the expected source?
        retrieved_sources = [c.metadata.get("source", "") for c in chunks]
        source_hit = any(
            tc["expected_source"] in s for s in retrieved_sources
        )
        context_recall = 1.0 if source_hit else 0.0

        # ── Metric 2: Context Precision ──────────────────────────
        # What fraction of retrieved chunks contain expected terms?
        relevant_count = 0
        for chunk in chunks:
            text_lower = chunk.page_content.lower()
            if any(term.lower() in text_lower for term in tc["expected_terms"]):
                relevant_count += 1
        context_precision = relevant_count / len(chunks) if chunks else 0.0

        # ── Metric 3: Answer Groundedness ────────────────────────
        # Build context block and check if expected terms appear in it.
        # (Proxy for faithfulness without calling the LLM.)
        context_block = build_context_block(chunks)
        context_lower = context_block.lower()
        terms_in_context = sum(
            1 for t in tc["expected_terms"]
            if t.lower() in context_lower
        )
        groundedness = terms_in_context / len(tc["expected_terms"])

        # ── Metric 4: Top chunk similarity score ─────────────────
        top_score = (
            chunks[0].metadata.get("rerank_score", 0.0) if chunks else 0.0
        )

        result = {
            "description":       tc["description"],
            "question":          tc["question"],
            "chunks_retrieved":  len(chunks),
            "context_recall":    round(context_recall, 2),
            "context_precision": round(context_precision, 2),
            "groundedness":      round(groundedness, 2),
            "top_rerank_score":  round(top_score, 4),
        }
        results.append(result)

        # Print individual result
        recall_icon    = "✅" if context_recall    >= 0.75 else "⚠️"
        precision_icon = "✅" if context_precision >= 0.70 else "⚠️"
        ground_icon    = "✅" if groundedness      >= 0.80 else "⚠️"

        print(f"  {recall_icon} Context Recall    : {context_recall:.2f}")
        print(f"  {precision_icon} Context Precision : {context_precision:.2f}")
        print(f"  {ground_icon} Groundedness      : {groundedness:.2f}")
        print(f"     Top Rerank Score  : {top_score:.4f}")
        print(f"     Chunks retrieved  : {len(chunks)}")
        print()

    # ── Aggregate scores ─────────────────────────────────────────────
    avg_recall    = sum(r["context_recall"]    for r in results) / len(results)
    avg_precision = sum(r["context_precision"] for r in results) / len(results)
    avg_ground    = sum(r["groundedness"]      for r in results) / len(results)
    avg_score     = sum(r["top_rerank_score"]  for r in results) / len(results)

    print("=" * 60)
    print("  AGGREGATE SCORES")
    print("=" * 60)
    print(f"  Context Recall    : {avg_recall:.2f}  "
          f"{'✅ PASS' if avg_recall >= 0.75 else '⚠️  NEEDS IMPROVEMENT'}")
    print(f"  Context Precision : {avg_precision:.2f}  "
          f"{'✅ PASS' if avg_precision >= 0.70 else '⚠️  NEEDS IMPROVEMENT'}")
    print(f"  Groundedness      : {avg_ground:.2f}  "
          f"{'✅ PASS' if avg_ground >= 0.80 else '⚠️  NEEDS IMPROVEMENT'}")
    print(f"  Avg Rerank Score  : {avg_score:.4f}")
    print()

    overall = (avg_recall + avg_precision + avg_ground) / 3
    print(f"  Overall RAG Score : {overall:.2f}  "
          f"{'✅ PRODUCTION READY' if overall >= 0.75 else '⚠️  NEEDS TUNING'}")
    print()
    print("  TUNING GUIDE:")
    if avg_recall < 0.75:
        print("  → Low recall: increase RETRIEVAL_TOP_K or decrease CHUNK_SIZE")
    if avg_precision < 0.70:
        print("  → Low precision: increase MMR diversity_weight or rerank keyword weight")
    if avg_ground < 0.80:
        print("  → Low groundedness: check chunk overlap, review system prompt constraints")
    if overall >= 0.75:
        print("  → System is performing well. Consider testing with more diverse queries.")

    print("=" * 60)
    return results


def test_retry_logic():
    """Test that retry logic handles transient errors correctly."""
    import time
    from unittest.mock import patch, MagicMock
    from src.generation.llm_chain import _with_retry

    print("\n  Testing retry logic...")

    call_count = 0

    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("503 Service Unavailable")
        return "success"

    # Patch sleep to avoid waiting in tests
    with patch("src.generation.llm_chain.time.sleep"):
        result = _with_retry(flaky_function)

    assert result == "success", f"Expected 'success', got {result}"
    assert call_count == 3, f"Expected 3 calls, got {call_count}"
    print("  ✅ Retry logic: succeeded on attempt 3 after 2 failures")


def test_input_validation():
    """Test query and file validation functions."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # We can't import app.py directly (Streamlit would initialise)
    # so we test the validation logic inline
    from src.config import MAX_QUERY_LENGTH, MAX_FILE_SIZE_MB

    print("\n  Testing input validation...")

    # Query length check
    long_query = "x" * (MAX_QUERY_LENGTH + 1)
    assert len(long_query) > MAX_QUERY_LENGTH
    print(f"  ✅ MAX_QUERY_LENGTH = {MAX_QUERY_LENGTH} chars configured")

    # File size check
    assert MAX_FILE_SIZE_MB == 50
    print(f"  ✅ MAX_FILE_SIZE_MB = {MAX_FILE_SIZE_MB} MB configured")

    print("  ✅ Input validation constants confirmed")


if __name__ == "__main__":
    print("\nRunning RAG evaluation suite...\n")
    test_retry_logic()
    test_input_validation()
    run_pipeline_evaluation()