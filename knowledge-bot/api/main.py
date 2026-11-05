from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
import re
import json
from contextlib import asynccontextmanager

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from api.limiter import limiter

from src.retrieval.retriever import Retriever
from src.retrieval.router import route_query
from src.retrieval.tabular_agent import run_tabular_query
from src.generation.llm_chain import stream_answer, condense_query, extract_citation_metadata, build_context_block
from src.config import (
    UPLOAD_DIR,
    MAX_FILE_SIZE_MB,
    SUPPORTED_EXTENSIONS,
    CORS_ORIGINS,
    ENVIRONMENT,
    MAX_QUERY_LENGTH,
    LLM_MODEL,
    LLM_PROVIDER,
    sanitize_filename,
    get_tenant_upload_dir,
)
from src.database import (
    engine,
    Base,
    get_db,
    run_db_migrations,
    check_and_reset_tenant_budget,
    record_tenant_token_usage,
)
from src.models import ChatSession, ChatMessage, User, Tenant
from src.telemetry import create_rag_trace, count_tokens, estimate_token_cost
from src.activity import log_activity
from api.dependencies import get_current_user
from api.auth import router as auth_router
from api.admin import router as admin_router
from api.platform import router as platform_router

api_logger = logging.getLogger("api.main")

# Strict CORS environment gate: Fail fast if production environment lacks explicit non-wildcard origins
if ENVIRONMENT == "production" and ("*" in (CORS_ORIGINS or []) or not CORS_ORIGINS):
    raise EnvironmentError("CORS wildcard ('*') is not permitted in production. Set CORS_ORIGINS.")

cors_allowed = CORS_ORIGINS if CORS_ORIGINS else ([] if ENVIRONMENT == "production" else ["*"])

# Initialize Retriever singleton
retriever = None

def get_retriever() -> Retriever:
    global retriever
    if retriever is None:
        retriever = Retriever()
    return retriever

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup: validate configuration, run migrations, warm singleton
    try:
        from src.config import validate_config
        validate_config()
        run_db_migrations()
        get_retriever()
    except Exception as e:
        api_logger.error(f"Application startup initialization warning: {e}", exc_info=True)
    yield
    # Application shutdown: cleanup database connection pool
    try:
        engine.dispose()
    except Exception:
        pass

app = FastAPI(title="Enterprise Knowledge Bot API", lifespan=lifespan)

# Mount rate limiting state & middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Security headers middleware (OWASP hardening)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if ENVIRONMENT == "production" or request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Setup CORS to allow Next.js frontend to communicate securely
cors_regex = None if ENVIRONMENT == "production" else r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|.*\.nurexia\.co)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed,
    allow_origin_regex=cors_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")
app.include_router(platform_router, prefix="/platform")

from fastapi.exceptions import RequestValidationError

# Standardized RFC 7807 Error Envelopes
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    retry_after = getattr(exc, "retry_after", 60)
    msg = str(exc.detail) if exc.detail else "Rate limit exceeded"
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": msg,
                "retry_after": retry_after,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "detail": msg
        },
        headers={"Retry-After": str(retry_after)}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters or payload structure.",
                "details": exc.errors(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "detail": exc.errors()
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "detail": exc.detail
        },
        headers=exc.headers
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    api_logger.error(f"Global unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred.",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "detail": f"Internal server error: {str(exc)}"
        }
    )

class QueryRequest(BaseModel):
    query: str
    session_id: int

class SessionTitleUpdate(BaseModel):
    title: str

@app.get("/health")
def health_check(detailed: bool = False):
    """
    Liveness probe endpoint.
    Returns lightweight health status, or full dependency diagnostics when detailed=True.
    """
    if detailed:
        return readiness_check()
    return {"status": "ok"}

@app.get("/ready")
@app.get("/health/ready")
def readiness_check():
    """
    Readiness probe endpoint.
    Performs deep dependency checks:
    - PostgreSQL database (SELECT 1)
    - Redis task queue / limiter
    - ChromaDB vector store heartbeat
    - Distributed object storage (S3 / MinIO) ping
    Returns HTTP 200 if all critical dependencies are ready, HTTP 503 if any critical dependency fails.
    """
    from sqlalchemy import text
    from src.storage import get_storage_provider
    import redis

    checks = {}
    is_ready = True

    # 1. Database check
    t0 = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
        }
    except Exception as e:
        is_ready = False
        checks["database"] = {
            "status": "error",
            "error": str(e)
        }

    # 2. Redis check
    t0 = time.perf_counter()
    try:
        from src.config import REDIS_URL
        r = redis.from_url(REDIS_URL, socket_timeout=2)
        r.ping()
        checks["redis"] = {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
        }
    except Exception as e:
        checks["redis"] = {
            "status": "degraded",
            "warning": str(e)
        }

    # 3. ChromaDB check
    t0 = time.perf_counter()
    try:
        r = get_retriever()
        hb = r.heartbeat()
        checks["chromadb"] = {
            "status": "ok",
            "heartbeat": hb,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
        }
    except Exception as e:
        is_ready = False
        checks["chromadb"] = {
            "status": "error",
            "error": str(e)
        }

    # 4. Storage check
    t0 = time.perf_counter()
    try:
        storage = get_storage_provider()
        ok = storage.ping()
        if ok:
            checks["storage"] = {
                "status": "ok",
                "backend": storage.__class__.__name__,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
            }
        else:
            is_ready = False
            checks["storage"] = {
                "status": "error",
                "backend": storage.__class__.__name__,
                "error": "Storage ping check failed"
            }
    except Exception as e:
        is_ready = False
        checks["storage"] = {
            "status": "error",
            "error": str(e)
        }

    payload = {
        "status": "ready" if is_ready else "unhealthy",
        "environment": ENVIRONMENT,
        "version": "2.2.0",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if not is_ready:
        return JSONResponse(status_code=503, content=payload)
    return payload

@app.get("/documents")
def list_documents(current_user: User = Depends(get_current_user)):
    r = get_retriever()
    sources = r.list_sources_by_type(user_id=current_user.id, tenant_id=current_user.tenant_id)
    return {"documents": sources["personal"], "global_documents": sources["global"]}

@app.post("/upload")
@limiter.limit("15/hour")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    get_retriever()

    try:
        clean_name = sanitize_filename(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate extension
    ext = Path(clean_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {SUPPORTED_EXTENSIONS}")

    # Read and check size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File too large. Max allowed: {MAX_FILE_SIZE_MB} MB")

    from src.storage import get_storage_provider, get_object_key
    storage = get_storage_provider()
    storage_key = get_object_key(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        filename=clean_name,
        is_global=False
    )

    # Stream upload bytes to object storage
    storage.upload_bytes(contents, storage_key)

    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    save_path = tenant_dir / clean_name
    try:
        save_path.write_bytes(contents)
    except Exception as io_err:
        api_logger.warning(f"Could not cache file locally: {io_err}")

    try:
        from src.worker import process_document
        task = process_document.delay(
            str(save_path),
            current_user.id,
            tenant_id=current_user.tenant_id,
            is_global=False,
            storage_key=storage_key
        )

        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="DOC_UPLOAD",
            category="KNOWLEDGE",
            description=f"Uploaded personal document '{clean_name}'",
            details={"filename": clean_name, "is_global": False, "task_id": task.id, "storage_key": storage_key}
        )

        return {"filename": clean_name, "status": "processing", "task_id": task.id, "storage_key": storage_key}
    except Exception as e:
        try:
            storage.delete_object(storage_key)
        except Exception:
            pass
        if save_path.exists():
            try:
                save_path.unlink()
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")
@limiter.limit("120/minute")
def get_task_status(
    request: Request,
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    from src.worker import celery_app
    res = celery_app.AsyncResult(task_id)

    # Multi-tenant IDOR boundary: check if task metadata belongs to caller's tenant
    task_tenant_id = None
    if isinstance(res.info, dict) and "tenant_id" in res.info:
        task_tenant_id = res.info.get("tenant_id")
    elif isinstance(res.result, dict) and "tenant_id" in res.result:
        task_tenant_id = res.result.get("tenant_id")

    if task_tenant_id is not None and not getattr(current_user, "is_platform_admin", False):
        if task_tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to inspect this background task.")

    progress = {}
    if res.state == "PROGRESS" and isinstance(res.info, dict):
        progress = {k: v for k, v in res.info.items() if k not in ("tenant_id", "user_id")}
    elif res.ready() and res.successful():
        progress = {"stage": "COMPLETED", "pct": 100, "msg": "Document indexed successfully"}
    elif res.ready() and res.failed():
        err_msg = str(res.result)
        if isinstance(res.info, dict) and "msg" in res.info:
            err_msg = res.info["msg"]
        progress = {"stage": "FAILED", "pct": 0, "msg": err_msg}

    result_data = None
    if res.successful():
        if isinstance(res.result, dict):
            result_data = {k: v for k, v in res.result.items() if k not in ("tenant_id", "user_id")}
        else:
            result_data = res.result
    elif res.failed():
        result_data = str(res.result)

    return {
        "task_id": task_id,
        "status": res.state,
        "ready": res.ready(),
        "successful": res.successful() if res.ready() else False,
        "result": result_data,
        "progress": progress,
    }

@app.get("/documents/{filename}/download")
def download_document(
    filename: str,
    presigned: bool = False,
    current_user: User = Depends(get_current_user)
):
    r = get_retriever()

    try:
        clean_name = sanitize_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Verify document access in ChromaDB
    where_filter = {
        "$and": [
            {"source": clean_name},
            {"tenant_id": current_user.tenant_id}
        ]
    }
    metadata = r._store._collection.get(where=where_filter, include=["metadatas"])
    if not metadata or not metadata.get("metadatas"):
        raise HTTPException(status_code=404, detail="Document not found.")

    meta = metadata["metadatas"][0]
    is_global = meta.get("is_global") == 1
    owner_id = meta.get("user_id")

    if not is_global and owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this document.")

    from src.storage import get_storage_provider, get_object_key
    from src.config import STORAGE_BACKEND
    storage = get_storage_provider()

    target_key = None
    if is_global:
        key_global = get_object_key(tenant_id=current_user.tenant_id, user_id=None, filename=clean_name, is_global=True)
        if storage.object_exists(key_global):
            target_key = key_global
    else:
        key_personal = get_object_key(tenant_id=current_user.tenant_id, user_id=current_user.id, filename=clean_name, is_global=False)
        if storage.object_exists(key_personal):
            target_key = key_personal

    if target_key:
        if presigned and STORAGE_BACKEND == "s3":
            url = storage.generate_presigned_url(target_key, expiration_seconds=900)
            return {"filename": clean_name, "download_url": url, "expires_in": 900}
        else:
            stream = storage.download_stream(target_key)
            return StreamingResponse(
                stream,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="{clean_name}"'}
            )

    # Local fallback if not in object storage
    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    file_path = tenant_dir / clean_name
    if file_path.exists():
        import io
        return StreamingResponse(
            io.BytesIO(file_path.read_bytes()),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{clean_name}"'}
        )

    raise HTTPException(status_code=404, detail="Document binary not found.")

@app.delete("/documents/{filename}")
def delete_document(filename: str, current_user: User = Depends(get_current_user)):
    r = get_retriever()

    try:
        clean_name = sanitize_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check ownership in ChromaDB within current tenant
    where_filter = {
        "$and": [
            {"source": clean_name},
            {"tenant_id": current_user.tenant_id}
        ]
    }
    metadata = r._store._collection.get(where=where_filter, include=["metadatas"])

    from src.storage import get_storage_provider, get_object_key
    storage = get_storage_provider()
    key_personal = get_object_key(tenant_id=current_user.tenant_id, user_id=current_user.id, filename=clean_name, is_global=False)
    key_global = get_object_key(tenant_id=current_user.tenant_id, user_id=None, filename=clean_name, is_global=True)
    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    file_path = tenant_dir / clean_name

    has_chroma = bool(metadata and metadata.get("metadatas"))
    has_storage = storage.object_exists(key_personal) or storage.object_exists(key_global)
    has_disk = file_path.exists()

    if not has_chroma and not has_storage and not has_disk:
        raise HTTPException(status_code=404, detail="Document not found.")

    is_global = False
    if has_chroma:
        meta = metadata["metadatas"][0]
        is_global = meta.get("is_global") == 1
        owner_id = meta.get("user_id")

        if not is_global and owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this document.")
        if is_global and current_user.role not in ["superadmin", "admin", "editor"]:
            raise HTTPException(status_code=403, detail="Forbidden: You must be an admin or editor to delete a company document.")
    elif storage.object_exists(key_global):
        is_global = True
        if current_user.role not in ["superadmin", "admin", "editor"]:
            raise HTTPException(status_code=403, detail="Forbidden: You must be an admin or editor to delete a company document.")

    # Delete chunks scoped to tenant
    if is_global or current_user.role in ["superadmin", "admin", "editor"]:
        deleted_count = r._store.delete_source(clean_name, user_id=None, tenant_id=current_user.tenant_id)
    else:
        deleted_count = r._store.delete_source(clean_name, user_id=current_user.id, tenant_id=current_user.tenant_id)

    # Cascade delete from object storage
    storage.delete_object(key_personal)
    if is_global or current_user.role in ["superadmin", "admin", "editor"]:
        storage.delete_object(key_global)

    # Delete physical file
    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    file_path = tenant_dir / clean_name
    file_deleted = False
    if file_path.exists():
        try:
            os.remove(file_path)
            file_deleted = True
        except Exception:
            pass

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="DOC_DELETE",
        category="KNOWLEDGE",
        description=f"Deleted document '{clean_name}' ({deleted_count} chunks purged)",
        details={"filename": clean_name, "is_global": is_global, "chunks_deleted": deleted_count}
    )

    return {"status": "deleted", "filename": clean_name, "file_deleted": file_deleted}

@app.post("/sessions")
def create_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = ChatSession(title="New Chat", user_id=current_user.id, tenant_id=current_user.tenant_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title}

@app.get("/sessions")
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == current_user.tenant_id
    ).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == current_user.tenant_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.timestamp.asc()).all()
    results = []
    for m in messages:
        sources_list = []
        if getattr(m, "sources_json", None):
            try:
                sources_list = json.loads(m.sources_json)
            except Exception:
                sources_list = []
        results.append({
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp,
            "sources": sources_list,
        })
    return results

@app.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == current_user.tenant_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"status": "deleted"}

@app.patch("/sessions/{session_id}")
def update_session(session_id: int, update: SessionTitleUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == current_user.tenant_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = update.title
    db.commit()
    return {"status": "updated", "title": session.title}

@app.post("/query")
@limiter.limit("30/minute")
def query_bot(
    request: Request,
    query_req: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if len(query_req.query) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Query exceeds maximum length of {MAX_QUERY_LENGTH} characters."
        )

    if not query_req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    # 0. Check Tenant Monthly Token Budget & Reset Window
    if current_user.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
        if tenant:
            check_and_reset_tenant_budget(tenant, db)
            if tenant.monthly_token_budget is not None and (tenant.current_month_tokens or 0) >= tenant.monthly_token_budget:
                raise HTTPException(
                    status_code=402,
                    detail="Monthly token budget exceeded. Contact your organization admin."
                )

    r = get_retriever()

    session = db.query(ChatSession).filter(
        ChatSession.id == query_req.session_id,
        ChatSession.user_id == current_user.id,
        ChatSession.tenant_id == current_user.tenant_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Root telemetry trace for request lifecycle
    trace = create_rag_trace(
        name="rag_query",
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        session_id=str(query_req.session_id),
        metadata={"query_length": len(query_req.query)},
    )

    # 1. Fetch recent conversation turns for multi-turn conversational memory (prior to current query)
    prior_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == query_req.session_id
    ).order_by(ChatMessage.timestamp.desc()).limit(6).all()
    prior_messages.reverse()

    chat_history = [
        {"role": m.role, "content": m.content}
        for m in prior_messages
    ]

    user_msg = ChatMessage(session_id=query_req.session_id, role="user", content=query_req.query)
    db.add(user_msg)
    db.commit()

    # 2. Contextual Query Condensation: rewrite follow-ups into standalone search questions
    effective_query = query_req.query
    if chat_history:
        with trace.span(
            name="query_condense",
            input_data={"query": query_req.query, "history_turns": len(chat_history)},
            metadata={"llm_model": LLM_MODEL, "history_turns": len(chat_history)}
        ) as span_condense:
            effective_query = condense_query(query_req.query, chat_history)
            span_condense.end(output={"effective_query": effective_query})

    start_time = time.time()

    # 3. Route Query scoped to tenant
    sources = r.list_sources(user_id=current_user.id, tenant_id=current_user.tenant_id)

    # Check if the user explicitly provided an @doc or !doc tag in their prompt
    has_explicit_tag = bool(re.search(r'[@!]([\w\.,_-]+)', query_req.query))
    if has_explicit_tag:
        is_tabular, target_file = route_query(query_req.query, sources)
    else:
        # For general queries and conversational follow-ups, route using effective_query (full context)
        is_tabular, target_file = route_query(effective_query, sources)

    if not target_file:
        query_lower = query_req.query.strip().lower()
        generic_words = ["summarize", "summarise", "summary", "give me a summary"]
        is_generic = query_lower in generic_words or query_lower.startswith("summarize ") or query_lower.startswith("summarise ")
        if is_generic:
            trace.end(output={"route": "warning_unspecified_document"})
            def generate_warning():
                warning_msg = "Please specify which document you would like me to summarize by tagging it with `@` or `!` (e.g., 'summarize @sample.txt')."
                yield warning_msg
                from src.database import SessionLocal
                with SessionLocal() as s_db:
                    bot_msg = ChatMessage(session_id=query_req.session_id, role="assistant", content=warning_msg)
                    s_db.add(bot_msg)
                    s_db.commit()
            return StreamingResponse(generate_warning(), media_type="text/plain")

    if is_tabular and target_file:
        def generate_tabular():
            from src.database import SessionLocal
            try:
                response = run_tabular_query(query_req.query, target_file, tenant_id=current_user.tenant_id)
                yield response
            except Exception as e:
                response = f"\n\n[Error executing tabular query: {str(e)}]"
                yield response

            # Tabular source citation metadata
            citations = [{
                "source": target_file,
                "chunk_id": f"tabular_{target_file}",
                "page": "Tabular Dataset",
                "content": f"In-memory SQLite database table derived from {target_file}.",
                "is_global": True,
                "relevance_rank": 1,
            }]
            sources_payload = json.dumps(citations)
            yield f"\n\n__SOURCES_METADATA_START__{sources_payload}__SOURCES_METADATA_END__"

            latency_ms = int((time.time() - start_time) * 1000)
            tabular_tokens = count_tokens(query_req.query + response, LLM_MODEL)
            if current_user.tenant_id:
                try:
                    with SessionLocal() as s_db:
                        record_tenant_token_usage(current_user.tenant_id, tabular_tokens, s_db)
                except Exception as db_err:
                    api_logger.error(f"Failed to record tabular token usage: {db_err}")

            trace.end(output={"route": "tabular", "tokens": tabular_tokens, "latency_ms": latency_ms})

            log_activity(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                action="QUERY_EXECUTED",
                category="QUERY",
                description=f"Tabular SQL query on '{target_file}' ({latency_ms}ms, {tabular_tokens} tokens)",
                details={
                    "query_preview": query_req.query[:100],
                    "target_file": target_file,
                    "route": "tabular",
                    "latency_ms": latency_ms,
                    "tokens": tabular_tokens
                }
            )

            with SessionLocal() as s_db:
                bot_msg = ChatMessage(
                    session_id=query_req.session_id,
                    role="assistant",
                    content=response,
                    sources_json=sources_payload
                )
                s_db.add(bot_msg)
                s_db.commit()

        return StreamingResponse(generate_tabular(), media_type="text/plain")

    # Fallback to standard semantic RAG search scoped to tenant using effective_query
    chunks = r.retrieve(
        effective_query,
        user_id=current_user.id,
        source_filter=target_file,
        tenant_id=current_user.tenant_id,
        trace=trace
    )

    citations = extract_citation_metadata(chunks)
    sources_payload = json.dumps(citations)

    def generate():
        from src.database import SessionLocal
        full_response = ""
        ttft = None
        stream_start = time.perf_counter()
        try:
            for chunk in stream_answer(effective_query, chunks, chat_history=chat_history):
                if ttft is None:
                    ttft = round((time.perf_counter() - stream_start) * 1000, 2)
                full_response += chunk
                yield chunk
        except Exception as e:
            error_msg = f"\n\n[Error generating response: {str(e)}]"
            full_response += error_msg
            yield error_msg

        # Append source citation metadata packet to stream
        yield f"\n\n__SOURCES_METADATA_START__{sources_payload}__SOURCES_METADATA_END__"

        latency_ms = int((time.time() - start_time) * 1000)

        # Telemetry & Cost Accounting
        context_text = build_context_block(chunks) if chunks else ""
        prompt_tokens = count_tokens(effective_query + "\n" + context_text, LLM_MODEL)
        completion_tokens = count_tokens(full_response, LLM_MODEL)
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = estimate_token_cost(prompt_tokens, completion_tokens, LLM_MODEL)

        with trace.span(
            name="llm_stream",
            input_data={"prompt_tokens": prompt_tokens},
            metadata={
                "ttft_ms": ttft or 0.0,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "chunks_used": len(chunks),
                "llm_provider": LLM_PROVIDER,
                "model": LLM_MODEL,
            }
        ) as llm_span:
            llm_span.end(output={"completion_tokens": completion_tokens, "cost_usd": cost_usd})

        if current_user.tenant_id:
            try:
                with SessionLocal() as s_db:
                    record_tenant_token_usage(current_user.tenant_id, total_tokens, s_db)
            except Exception as db_err:
                api_logger.error(f"Failed to record RAG token usage: {db_err}")

        trace.record_generation(
            name="rag_completion",
            model=LLM_MODEL,
            prompt=effective_query,
            completion=full_response,
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens},
            metadata={"cost_usd": cost_usd, "ttft_ms": ttft or 0.0}
        )
        trace.end(output={"total_tokens": total_tokens, "cost_usd": cost_usd})

        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="QUERY_EXECUTED",
            category="QUERY",
            description=f"RAG query executed ({len(chunks)} chunks, {total_tokens} tokens, {latency_ms}ms)",
            details={
                "query_preview": query_req.query[:100],
                "effective_query": effective_query[:100] if effective_query != query_req.query else None,
                "target_file": target_file,
                "route": "semantic",
                "chunks_count": len(chunks),
                "latency_ms": latency_ms,
                "tokens": total_tokens,
                "cost_usd": cost_usd,
                "ttft_ms": ttft or 0.0
            }
        )

        with SessionLocal() as s_db:
            bot_msg = ChatMessage(
                session_id=query_req.session_id,
                role="assistant",
                content=full_response,
                sources_json=sources_payload
            )
            s_db.add(bot_msg)
            s_db.commit()

    return StreamingResponse(generate(), media_type="text/plain")
