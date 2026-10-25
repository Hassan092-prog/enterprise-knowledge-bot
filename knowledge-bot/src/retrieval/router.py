import json
import re
from typing import List, Optional, Tuple
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from src.llm_factory import get_llm
from src.config import LLM_PROVIDER

from src.logger import get_logger

logger = get_logger(__name__)

# Very simple router to detect if a query targets a specific CSV document
ROUTER_PROMPT = """You are a precision query routing assistant.
The user has uploaded these structured CSV datasets:
{documents}

The user's query is: "{query}"

Determine whether this question specifically targets one of the CSV datasets above for numerical calculations, counting rows, or structured tabular analysis (e.g., employee salaries, headcounts, or roster metrics).

Rules:
1. ONLY set "is_tabular": true if the query is specifically about data residing in one of the CSV files listed above.
2. If the question asks about company financial reports, reviews, text documents, executive summaries, technical manuals, or general knowledge, set "is_tabular": false and "target_file": null.
3. If unsure, ALWAYS default to "is_tabular": false and "target_file": null.

{format_instructions}
"""

def route_query(query: str, available_documents: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Determines if the query should be routed to the tabular agent (Pandas)
    and if so, which file it targets.
    """
    match = re.search(r'[@!]([\w\.,_-]+)', query)
    if match:
        tagged_file = match.group(1)
        for doc in available_documents:
            if tagged_file.lower() in doc.lower():
                logger.info(f"Explicit mention routing detected: {tagged_file} -> {doc}")
                is_tabular = doc.lower().endswith('.csv')
                return is_tabular, doc
                
    # Allow files ending in .csv
    csv_docs = [
        d for d in available_documents 
        if d.lower().endswith('.csv')
    ]
    
    if not csv_docs:
        return False, None
        
    if LLM_PROVIDER == "groq":
        router_model = "openai/gpt-oss-120b"
    elif LLM_PROVIDER == "mistral":
        router_model = "mistral-large-latest"
    else:
        router_model = "gpt-4o-mini"
        
    llm = get_llm(temperature=0, model=router_model)
        
    parser = JsonOutputParser()
    prompt = PromptTemplate(
        template=ROUTER_PROMPT,
        input_variables=["documents", "query"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )
    
    chain = prompt | llm | parser
    
    try:
        data = chain.invoke({"documents": ", ".join(csv_docs), "query": query})
        is_tabular = data.get("is_tabular", False)
        target = data.get("target_file")
        
        # Verify the target actually exists in the available CSV docs
        if is_tabular and target:
            target_clean = str(target).strip().lower()
            # 1. Exact match
            for doc in csv_docs:
                if target_clean == doc.lower() or target_clean == doc.lower().replace(".csv", ""):
                    return True, doc
                    
            # 2. Substring match
            for doc in csv_docs:
                clean_name = doc.lower().replace(".csv", "")
                if target_clean in doc.lower() or clean_name in target_clean:
                    return True, doc
                    
        # If not confidently matched to a specific CSV, route to standard semantic search
        return False, None
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        # To debug the exact output that broke the JsonOutputParser, we could 
        # log the raw LLM output here in the future if we catch OutputParserException
        
    return False, None
