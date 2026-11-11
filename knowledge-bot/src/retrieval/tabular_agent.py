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

def run_tabular_query(query: str, filename: str, tenant_id: Optional[int] = None, user_id: Optional[int] = None) -> str:
    """
    Runs a query on a specific CSV file using a SQL Agent on an in-memory SQLite database,
    partitioned securely by tenant_id and user-personal scoping with strict path traversal prevention.
    """
    try:
        clean_name = sanitize_filename(filename)
    except Exception as e:
        return f"Invalid filename: {e}"

    upload_root = UPLOAD_DIR.resolve()
    tenant_dir = get_tenant_upload_dir(tenant_id) if tenant_id is not None else UPLOAD_DIR
    personal_path = (tenant_dir / "personal" / str(user_id) / clean_name) if (tenant_id is not None and user_id is not None) else None
    global_path = tenant_dir / clean_name

    def _is_within_jail(p: Path) -> bool:
        try:
            return p.resolve().is_relative_to(upload_root)
        except Exception:
            return False

    file_path: Optional[Path] = None
    if personal_path is not None:
        if not _is_within_jail(personal_path):
            logger.error("Path traversal attempt blocked: %s", filename)
            return "Access denied: invalid file path."
        if personal_path.exists():
            file_path = personal_path

    if file_path is None:
        if not _is_within_jail(global_path):
            logger.error("Path traversal attempt blocked: %s", filename)
            return "Access denied: invalid file path."
        if global_path.exists():
            file_path = global_path
        elif tenant_id == 1:
            fallback_path = UPLOAD_DIR / clean_name
            if _is_within_jail(fallback_path) and fallback_path.exists():
                file_path = fallback_path

    if file_path is None:
        # Retrieve CSV strictly from caller's personal object key or tenant global object key
        try:
            from src.storage import get_storage_provider, get_object_key
            storage = get_storage_provider()
            content_bytes = None
            target_cache_path = None

            if tenant_id is not None and user_id is not None:
                key_personal = get_object_key(tenant_id=tenant_id, user_id=user_id, filename=clean_name, is_global=False)
                if storage.object_exists(key_personal):
                    content_bytes = storage.download_bytes(key_personal)
                    target_cache_path = personal_path

            if content_bytes is None:
                key_global = get_object_key(tenant_id=tenant_id, user_id=None, filename=clean_name, is_global=True)
                if storage.object_exists(key_global):
                    content_bytes = storage.download_bytes(key_global)
                    target_cache_path = global_path

            if content_bytes and target_cache_path is not None and _is_within_jail(target_cache_path):
                target_cache_path.parent.mkdir(parents=True, exist_ok=True)
                target_cache_path.write_bytes(content_bytes)
                file_path = target_cache_path
                logger.info(f"Retrieved and cached {clean_name} from object storage for tabular query.")
        except Exception as storage_err:
            logger.warning(f"Failed to fetch {clean_name} from storage: {storage_err}")

    if file_path is None or not file_path.exists():
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

    engine = None
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
            "You are an expert SQL analyst querying an in-memory SQLite database table named 'data'.\n"
            f"The table is named 'data'. Always query from table 'data'.\n"
            f"Available columns in table 'data': {columns_list}.\n"
            "COMPUTED METRICS & DERIVATIONS:\n"
            "- If the user asks for a derived or composite metric (such as 'total compensation', 'total payroll', 'total remuneration') that can be calculated by combining or summing available numeric columns (e.g. Base_Salary_USD + COALESCE(Annual_Bonus_USD, 0)), ALWAYS proactively compute it in SQLite, state the computed numerical total clearly, and mention the formula or columns combined.\n"
            "- Do NOT stop to ask permission if the metric can be calculated with SQL. Always execute the query and deliver the computed answer directly.\n"
            "- If the user asks about an attribute or metric that does NOT exist and CANNOT be computed from these columns, explicitly state that this metric is not in the dataset and list the available columns.\n\n"
            "DATA VISUALIZATION RULES:\n"
            "1. When the question involves a comparison, distribution, ranking, or breakdown across 2 or more categories "
            "(e.g., salary by department, headcount comparison, counts by role, spending by team):\n"
            "   - First provide your clear textual summary or markdown table.\n"
            "   - Then at the very end of your final response, append a chart specification in a fenced code block with language 'chart':\n"
            "```chart\n"
            "{{\n"
            '  "type": "bar",\n'
            '  "title": "Descriptive Chart Title",\n'
            '  "labels": ["Category A", "Category B", "Category C"],\n'
            '  "series": [\n'
            '    {{\n'
            '      "name": "Metric Name",\n'
            '      "data": [120, 250, 180]\n'
            '    }}\n'
            '  ]\n'
            "}}\n"
            "```\n"
            "2. If the user only asks for a single scalar value (e.g. 'Who is the highest paid person?', 'What is the overall average salary?'), "
            "do NOT include a chart block; answer directly."
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
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
