from langchain_community.agent_toolkits import create_sql_agent, SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from sqlalchemy import create_engine
from src.llm_factory import get_llm
import pandas as pd
import os
from pathlib import Path
from src.config import UPLOAD_DIR, LLM_PROVIDER
from src.logger import get_logger

logger = get_logger(__name__)

def run_tabular_query(query: str, filename: str) -> str:
    """
    Runs a query on a specific CSV file using a SQL Agent on an in-memory SQLite database.
    """
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        return f"File {filename} not found."
    
    try:
        df = pd.read_csv(file_path, on_bad_lines='skip', engine='python')
    except Exception as e:
        logger.error(f"Error reading {filename} as CSV: {e}")
        return f"Error reading {filename} as CSV: {str(e)}"
        
    if df.empty:
        return f"The file {filename} is empty or could not be parsed correctly."
        
    llm = get_llm(temperature=0, model="mistral-large-latest" if LLM_PROVIDER == "mistral" else "gpt-4o-mini")
    
    try:
        # Load CSV into an in-memory SQLite database
        engine = create_engine("sqlite:///:memory:")
        df.to_sql("data", engine, index=False, if_exists="replace")
        db = SQLDatabase(engine)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        
        agent = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            agent_type="tool-calling",
            verbose=True,
            handle_parsing_errors=True
        )
    except Exception as e:
        logger.error(f"Error creating SQL agent: {e}")
        return f"Error creating tabular agent: {str(e)}"
    
    try:
        response = agent.invoke({"input": query})
        return response.get("output", "No output generated.")
    except Exception as e:
        logger.error(f"Tabular query error: {e}")
        return f"Error executing tabular query: {str(e)}"
