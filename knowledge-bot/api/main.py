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

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from api.limiter import limiter

from src.retrieval.retriever import Retriever
from src.retrieval.router import route_query
from src.retrieval.tabular_agent import run_tabular_query
from src.generation.llm_chain import stream_answer, condense_query, extract_citation_metadata
from src.config import (
    UPLOAD_DIR,
    MAX_FILE_SIZE_MB,
    SUPPORTED_EXTENSIONS,
    CORS_ORIGINS,
    ENVIRONMENT,
    MAX_QUERY_LENGTH,
    sanitize_filename,
    get_tenant_upload_dir,
)
from src.database import engine, Base, get_db, run_db_migrations
from src.models import ChatSession, ChatMessage, User
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

app = FastAPI(title="Enterprise Knowledge Bot API")

# Mount rate limiting state & middleware
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# Setup CORS to allow Next.js frontend to communicate securely
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|.*\.nurexia\.co)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")
app.include_router(platform_router, prefix="/platform")

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

# Initialize Retriever singleton
retriever = None

@app.on_event("startup")
async def startup_event():
    global retriever
    from src.config import validate_config
    validate_config()
    run_db_migrations()
    retriever = Retriever()

class QueryRequest(BaseModel):
    query: str
    session_id: int

class SessionTitleUpdate(BaseModel):
    title: str

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/documents")
def list_documents(current_user: User = Depends(get_current_user)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    sources = retriever.list_sources_by_type(user_id=current_user.id, tenant_id=current_user.tenant_id)
    return {"documents": sources["personal"], "global_documents": sources["global"]}

@app.post("/upload")
@limiter.limit("15/hour")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

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

    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    save_path = tenant_dir / clean_name
    save_path.write_bytes(contents)

    try:
        from src.worker import process_document
        task = process_document.delay(
            str(save_path),
            current_user.id,
            tenant_id=current_user.tenant_id,
            is_global=False
        )

        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="DOC_UPLOAD",
            category="KNOWLEDGE",
            description=f"Uploaded personal document '{clean_name}'",
            details={"filename": clean_name, "is_global": False, "task_id": task.id}
        )

        return {"filename": clean_name, "status": "processing", "task_id": task.id}
    except Exception as e:
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

@app.delete("/documents/{filename}")
def delete_document(filename: str, current_user: User = Depends(get_current_user)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

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
    metadata = retriever._store._collection.get(where=where_filter, include=["metadatas"])

    is_global = False
    if metadata and metadata.get("metadatas"):
        meta = metadata["metadatas"][0]
        is_global = meta.get("is_global") == 1
        owner_id = meta.get("user_id")

        if not is_global and owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this document.")
        if is_global and current_user.role not in ["superadmin", "admin", "editor"]:
            raise HTTPException(status_code=403, detail="Forbidden: You must be an admin or editor to delete a company document.")

    # Delete chunks scoped to tenant
    if is_global or current_user.role in ["superadmin", "admin", "editor"]:
        deleted_count = retriever._store.delete_source(clean_name, user_id=None, tenant_id=current_user.tenant_id)
    else:
        deleted_count = retriever._store.delete_source(clean_name, user_id=current_user.id, tenant_id=current_user.tenant_id)

    # Delete physical file
    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    file_path = tenant_dir / clean_name
    file_deleted = False
    if file_path.exists():
        os.remove(file_path)
        file_deleted = True

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
        ChatSession.user_id == current_user.id
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
        ChatSession.user_id == current_user.id
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
        ChatSession.user_id == current_user.id
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

    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

    session = db.query(ChatSession).filter(
        ChatSession.id == query_req.session_id,
        ChatSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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
        effective_query = condense_query(query_req.query, chat_history)

    start_time = time.time()

    # 3. Route Query scoped to tenant
    sources = retriever.list_sources(user_id=current_user.id, tenant_id=current_user.tenant_id)

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
            log_activity(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                action="QUERY_EXECUTED",
                category="QUERY",
                description=f"Tabular SQL query on '{target_file}' ({latency_ms}ms)",
                details={
                    "query_preview": query_req.query[:100],
                    "target_file": target_file,
                    "route": "tabular",
                    "latency_ms": latency_ms
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
    chunks = retriever.retrieve(
        effective_query,
        user_id=current_user.id,
        source_filter=target_file,
        tenant_id=current_user.tenant_id
    )

    citations = extract_citation_metadata(chunks)
    sources_payload = json.dumps(citations)

    def generate():
        from src.database import SessionLocal
        full_response = ""
        try:
            for chunk in stream_answer(effective_query, chunks, chat_history=chat_history):
                full_response += chunk
                yield chunk
        except Exception as e:
            error_msg = f"\n\n[Error generating response: {str(e)}]"
            full_response += error_msg
            yield error_msg

        # Append source citation metadata packet to stream
        yield f"\n\n__SOURCES_METADATA_START__{sources_payload}__SOURCES_METADATA_END__"

        latency_ms = int((time.time() - start_time) * 1000)
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="QUERY_EXECUTED",
            category="QUERY",
            description=f"RAG query executed ({len(chunks)} chunks retrieved, {latency_ms}ms)",
            details={
                "query_preview": query_req.query[:100],
                "effective_query": effective_query[:100] if effective_query != query_req.query else None,
                "target_file": target_file,
                "route": "semantic",
                "chunks_count": len(chunks),
                "latency_ms": latency_ms
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
