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

@celery_app.task(name="process_document", bind=True)
def process_document(
    self,
    file_path: Optional[str] = None,
    user_id: int = 0,
    tenant_id: Optional[int] = None,
    is_global: bool = False,
    storage_key: Optional[str] = None,
):
    global retriever
    if retriever is None:
        from src.config import validate_config
        from src.database import Base, engine
        validate_config()
        # Ensure tables exist (optional for worker, but safe)
        Base.metadata.create_all(bind=engine)
        from src.retrieval.retriever import Retriever
        retriever = Retriever()

    def _on_progress(stage: str, pct: int, msg: str = ""):
        self.update_state(
            state="PROGRESS",
            meta={
                "stage": stage,
                "pct": pct,
                "msg": msg,
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
        )

    _on_progress("PARSING", 5, "Initializing background ingestion pipeline...")

    from pathlib import Path
    from src.storage import get_storage_provider, get_object_key
    storage = get_storage_provider()
    target_user_id = None if is_global else user_id

    filename = None
    if file_path:
        filename = Path(file_path).name
    elif storage_key:
        filename = Path(storage_key).name

    logger.info(f"Starting background ingestion for {filename or file_path or storage_key} (user={user_id}, tenant={tenant_id}, global={is_global}, storage_key={storage_key})")
    try:
        input_source = None
        if storage_key and storage.object_exists(storage_key):
            logger.info(f"Streaming document from object storage: {storage_key}")
            input_source = storage.download_stream(storage_key)
        elif file_path and Path(file_path).is_file():
            logger.info(f"Reading document from local file: {file_path}")
            input_source = Path(file_path)
        else:
            computed_key = get_object_key(tenant_id=tenant_id, user_id=target_user_id, filename=filename, is_global=is_global)
            if storage.object_exists(computed_key):
                logger.info(f"Streaming document from computed object storage key: {computed_key}")
                input_source = storage.download_stream(computed_key)
            elif file_path:
                input_source = Path(file_path)
            else:
                raise FileNotFoundError(f"Document not found on storage or disk (storage_key={storage_key}, file_path={file_path})")

        import inspect
        sig = inspect.signature(retriever.ingest_file)
        kwargs = {
            "file_path": input_source,
            "user_id": target_user_id,
            "is_global": is_global,
            "tenant_id": tenant_id,
            "filename": filename,
        }
        if "progress_callback" in sig.parameters:
            kwargs["progress_callback"] = _on_progress

        result = retriever.ingest_file(**kwargs)

        doc_display_name = filename or (Path(file_path).name if file_path else "document")
        logger.info(f"Successfully ingested {doc_display_name}. Added {result.chunks_added} chunks.")
        
        # Async activity log if tenant_id is available
        if tenant_id:
            try:
                from src.activity import log_activity
                doc_type = "company" if is_global else "personal"
                log_activity(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action="DOC_INDEXED",
                    category="KNOWLEDGE",
                    description=f"Indexed {doc_type} document '{doc_display_name}' ({result.chunks_added} chunks)",
                    details={
                        "filename": doc_display_name,
                        "chunks_added": result.chunks_added,
                        "total_chunks": result.total_chunks,
                        "is_global": is_global,
                        "storage_key": storage_key,
                    }
                )
            except Exception as act_err:
                logger.warning(f"Failed to record DOC_INDEXED activity: {act_err}")

        _on_progress("COMPLETED", 100, f"Indexed {result.chunks_added} chunks.")
        return {
            "filename": doc_display_name,
            "chunks_added": result.chunks_added,
            "total_chunks": result.total_chunks,
            "already_existed": result.already_existed,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "storage_key": storage_key,
        }
    except Exception as e:
        logger.error(f"Error ingesting {filename or file_path or storage_key}: {e}")
        self.update_state(
            state="FAILURE",
            meta={
                "stage": "FAILED",
                "pct": 0,
                "msg": str(e),
                "tenant_id": tenant_id,
                "user_id": user_id,
            }
        )
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
