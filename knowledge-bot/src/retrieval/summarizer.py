from src.llm_factory import get_llm
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document
from typing import List

from src.logger import get_logger

logger = get_logger(__name__)

SUMMARY_PROMPT = """
You are an expert summarizer. Please write a comprehensive executive summary of the following document.
Capture the main topics, key findings, and important details.

Document Content:
{text}

Summary:
"""

def generate_document_summary(documents: List[Document]) -> str:
    """
    Generates a single summary for a list of documents (usually from a single file).
    If the document is too large, it truncates the text to fit in the context window.
    """
    if not documents:
        return "No content to summarize."
        
    # Combine content up to a reasonable limit (~30k chars for gpt-4o-mini)
    full_text = "\n\n".join(doc.page_content for doc in documents)
    full_text = full_text[:30000] 
    
    llm = get_llm(temperature=0)
    prompt = PromptTemplate.from_template(SUMMARY_PROMPT)
    
    try:
        logger.info("Generating summary for document...")
        response = llm.invoke(prompt.format(text=full_text))
        return response.content.strip()
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        return "Summary could not be generated."
