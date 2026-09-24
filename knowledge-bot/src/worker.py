import os
from celery import Celery
from src.retrieval.retriever import Retriever
from src.logger import get_logger

logger = get_logger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("knowledge_bot_worker", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Initialize Retriever once per worker process
retriever = None

@celery_app.task(name="process_document")
def process_document(file_path: str, user_id: int):
    global retriever
    if retriever is None:
        from src.config import validate_config
        from src.database import Base, engine
        validate_config()
        # Ensure tables exist (optional for worker, but safe)
        Base.metadata.create_all(bind=engine)
        retriever = Retriever()

    logger.info(f"Starting background ingestion for {file_path}")
    try:
        from pathlib import Path
        result = retriever.ingest_file(Path(file_path), user_id)
        logger.info(f"Successfully ingested {file_path}. Added {result.chunks_added} chunks.")
        return {"filename": Path(file_path).name, "chunks_added": result.chunks_added}
    except Exception as e:
        logger.error(f"Error ingesting {file_path}: {e}")
        raise e
