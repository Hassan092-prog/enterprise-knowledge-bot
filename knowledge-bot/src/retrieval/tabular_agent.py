import re
from pathlib import Path
from typing import Optional
import pandas as pd
from sqlalchemy import create_engine
from langchain_community.agent_toolkits import create_sql_agent, SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase

from src.llm_factory import get_llm
from src.config import UPLOAD_DIR, LLM_PROVIDER, sanitize_filename, get_tenant_upload_dir
from src.logger import get_logger

logger = get_logger(__name__)

def run_tabular_query(query: str, filename: str, tenant_id: Optional[int] = None) -> str:
    """
    Runs a query on a specific CSV file using a SQL Agent on an in-memory SQLite database,
    partitioned securely by tenant_id with strict path traversal prevention.
    """
    try:
        clean_name = sanitize_filename(filename)
    except Exception as e:
        return f"Invalid filename: {e}"

    # Determine file path based on tenant
    if tenant_id is not None:
        tenant_dir = get_tenant_upload_dir(tenant_id)
        file_path = tenant_dir / clean_name
        # Fallback to root upload dir if file was uploaded prior to multi-tenancy
        if not file_path.exists():
            fallback_path = UPLOAD_DIR / clean_name
            if fallback_path.exists():
                file_path = fallback_path
    else:
        file_path = UPLOAD_DIR / clean_name

    # Enforce filesystem jail check
    try:
        resolved = file_path.resolve()
        upload_root = UPLOAD_DIR.resolve()
        if not str(resolved).startswith(str(upload_root)):
            logger.error("Path traversal attempt blocked: %s", filename)
            return "Access denied: invalid file path."
    except Exception as e:
        return f"Path verification failed: {e}"

    if not file_path.exists():
        return f"File {filename} not found in your organization's repository."

    try:
        df = pd.read_csv(file_path, on_bad_lines='skip', engine='python')
    except Exception as e:
        logger.error(f"Error reading {filename} as CSV: {e}")
        return f"Error reading {filename} as CSV: {str(e)}"

    if df.empty:
        return f"The file {filename} is empty or could not be parsed correctly."

    if LLM_PROVIDER == "groq":
        tabular_model = "openai/gpt-oss-120b"
    elif LLM_PROVIDER == "mistral":
        tabular_model = "mistral-large-latest"
    else:
        tabular_model = "gpt-4o-mini"

    llm = get_llm(temperature=0, model=tabular_model)

    try:
        # Load CSV into an in-memory SQLite database
        engine = create_engine("sqlite:///:memory:")
        clean_table = re.sub(r'[^a-zA-Z0-9_]', '_', Path(clean_name).stem)
        df.to_sql("data", engine, index=False, if_exists="replace")
        if clean_table != "data":
            df.to_sql(clean_table, engine, index=False, if_exists="replace")

        db = SQLDatabase(engine)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        columns_list = ", ".join(df.columns.tolist())
        prefix = (
            "You are an expert SQL assistant querying an in-memory SQLite database.\n"
            f"The table is named 'data'. Always query from table 'data'.\n"
            f"Available columns in table 'data': {columns_list}.\n"
            "Do NOT try to query tables matching the raw filename. Always use table 'data'.\n"
            "If the user asks about an attribute or metric that does not exist in these columns, "
            "explicitly state that this metric is not in the dataset and list the available columns."
        )

        agent_type = "tool-calling" if LLM_PROVIDER != "mistral" else "zero-shot-react-description"
        agent = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            agent_type=agent_type,
            prefix=prefix,
            max_iterations=6,
            verbose=True,
            handle_parsing_errors=True
        )
    except Exception as e:
        logger.error(f"Error creating SQL agent: {e}")
        return f"Error creating tabular agent: {str(e)}"

    try:
        response = agent.invoke({"input": query})
        output = response.get("output", "No output generated.")
        if output.strip().lower().rstrip(".") == "i don't know":
            return (
                f"I could not find that information in `{filename}` because the requested metric is not in the dataset.\n\n"
                f"**Available columns:** {columns_list}"
            )
        return output
    except Exception as e:
        logger.error(f"Tabular query error: {e}")
        return f"Error executing tabular query: {str(e)}"
