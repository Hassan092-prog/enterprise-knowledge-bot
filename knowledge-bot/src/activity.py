import json
from typing import Optional, Any
from src.logger import get_logger

logger = get_logger(__name__)

def log_activity(
    tenant_id: int,
    user_id: Optional[int],
    action: str,
    category: str,
    description: str,
    details: Optional[Any] = None
):
    """
    Asynchronously record an activity log entry via Celery.
    Non-blocking with fail-safe logging if Celery/broker is unavailable.
    """
    if not tenant_id:
        logger.warning(f"log_activity skipped: missing tenant_id for action={action}")
        return

    details_json = None
    if details is not None:
        try:
            if isinstance(details, str):
                details_json = details
            else:
                details_json = json.dumps(details, default=str)
        except Exception as e:
            logger.warning(f"Failed to serialize activity details: {e}")
            details_json = str(details)

    try:
        from src.worker import log_activity_async
        log_activity_async.delay(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            category=category,
            description=description,
            details_json=details_json
        )
    except Exception as e:
        logger.warning(f"Failed to dispatch async activity log (fallback mode): {e}")
        try:
            # Synchronous fallback in case worker queue is down
            from src.database import SessionLocal
            from src.models import ActivityLog
            with SessionLocal() as db:
                entry = ActivityLog(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=action,
                    category=category,
                    description=description,
                    details=details_json
                )
                db.add(entry)
                db.commit()
        except Exception as inner_e:
            logger.error(f"Failed direct activity log write: {inner_e}")
