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
ROUTER_PROMPT = """
You are a routing assistant. The user has uploaded the following documents:
{documents}

The user asks: "{query}"

If the user's question requires aggregating, calculating, counting rows, or analyzing tabular/structured data from any of the provided documents, output a JSON object with:
- "is_tabular": true
- "target_file": "pick the closest matching exact filename from the list above, even if the user misspelled it or added .csv"

Otherwise, output:
- "is_tabular": false
- "target_file": null

{format_instructions}
"""

def route_query(query: str, available_documents: List[str]) -> Tuple[bool, Optional[str]]:
    """
    Determines if the query should be routed to the tabular agent (Pandas)
    and if so, which file it targets.
    """
    match = re.search(r'!([\w\.,_-]+)', query)
    if match:
        tagged_file = match.group(1)
        for doc in available_documents:
            if tagged_file.lower() in doc.lower():
                logger.info(f"Explicit !filename routing detected: {tagged_file} -> {doc}")
                is_tabular = doc.lower().endswith('.csv')
                return is_tabular, doc
                
    # Allow files ending in .csv
    csv_docs = [
        d for d in available_documents 
        if d.lower().endswith('.csv')
    ]
    
    if not csv_docs:
        return False, None
        
    llm = get_llm(temperature=0, model="mistral-large-latest" if LLM_PROVIDER == "mistral" else "gpt-4o-mini")
        
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
        
        # Verify the target actually exists in the available docs
        if is_tabular:
            # 1. Exact match
            if target and target in csv_docs:
                return True, target
                
            # 2. Substring match
            if target:
                for doc in csv_docs:
                    target_clean = target.lower().replace(".csv", "")
                    if target_clean in doc.lower() or doc.lower() in target_clean:
                        return True, doc
                        
            # 3. Fallback: just return the first file that looks like a CSV (not a .txt)
            for doc in csv_docs:
                if not doc.lower().endswith(".txt"):
                    return True, doc
                    
            # 4. Desperation fallback
            if csv_docs:
                return True, csv_docs[0]
                
        return False, None
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        # To debug the exact output that broke the JsonOutputParser, we could 
        # log the raw LLM output here in the future if we catch OutputParserException
        
    return False, None
