import os
from datetime import datetime, timedelta
from typing import Optional
from celery import Celery
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
def process_document(file_path: str, user_id: int, tenant_id: Optional[int] = None, is_global: bool = False):
    global retriever
    if retriever is None:
        from src.config import validate_config
        from src.database import Base, engine
        validate_config()
        # Ensure tables exist (optional for worker, but safe)
        Base.metadata.create_all(bind=engine)
        from src.retrieval.retriever import Retriever
        retriever = Retriever()

    logger.info(f"Starting background ingestion for {file_path} (user={user_id}, tenant={tenant_id}, global={is_global})")
    try:
        from pathlib import Path
        # Call ingest_file; in Phase 2 it will support tenant_id
        import inspect
        sig = inspect.signature(retriever.ingest_file)
        if "tenant_id" in sig.parameters:
            result = retriever.ingest_file(Path(file_path), user_id=user_id, is_global=is_global, tenant_id=tenant_id)
        else:
            result = retriever.ingest_file(Path(file_path), user_id=user_id, is_global=is_global)

        logger.info(f"Successfully ingested {file_path}. Added {result.chunks_added} chunks.")
        
        # Async activity log if tenant_id is available
        if tenant_id:
            try:
                from src.activity import log_activity
                log_activity(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action="DOC_INDEXED",
                    category="KNOWLEDGE",
                    description=f"Indexed document '{Path(file_path).name}' ({result.chunks_added} chunks)",
                    details={
                        "filename": Path(file_path).name,
                        "chunks_added": result.chunks_added,
                        "total_chunks": result.total_chunks,
                        "is_global": is_global
                    }
                )
            except Exception as act_err:
                logger.warning(f"Failed to record DOC_INDEXED activity: {act_err}")

        return {"filename": Path(file_path).name, "chunks_added": result.chunks_added}
    except Exception as e:
        logger.error(f"Error ingesting {file_path}: {e}")
        raise e


@celery_app.task(name="log_activity_async")
def log_activity_async(tenant_id: int, user_id: Optional[int], action: str, category: str, description: str, details_json: Optional[str] = None):
    """Celery task to record activity log asynchronously."""
    try:
        from src.database import SessionLocal
        from src.models import ActivityLog
        with SessionLocal() as db:
            entry = ActivityLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                category=category,
                description=description,
                details=details_json,
                timestamp=datetime.utcnow()
            )
            db.add(entry)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to execute log_activity_async: {e}")
        raise e


@celery_app.task(name="cleanup_old_activity_logs")
def cleanup_old_activity_logs(retention_days: int = 90):
    """Celery task to purge activity logs older than retention period."""
    try:
        from src.database import SessionLocal
        from src.models import ActivityLog
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        with SessionLocal() as db:
            deleted = db.query(ActivityLog).filter(ActivityLog.timestamp < cutoff).delete(synchronize_session=False)
            db.commit()
            logger.info(f"Purged {deleted} activity log records older than {retention_days} days.")
            return {"deleted_count": deleted}
    except Exception as e:
        logger.error(f"Failed to cleanup old activity logs: {e}")
        raise e
