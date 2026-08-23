from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
import os
from pathlib import Path
from sqlalchemy.orm import Session

from src.retrieval.retriever import Retriever
from src.retrieval.router import route_query
from src.retrieval.tabular_agent import run_tabular_query
from src.generation.llm_chain import stream_answer
from src.config import UPLOAD_DIR, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS
from src.database import engine, Base, get_db
from src.models import ChatSession, ChatMessage, User
from api.dependencies import get_current_user
from api.auth import router as auth_router
from api.admin import router as admin_router

app = FastAPI(title="Enterprise Knowledge Bot API")

app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")

# Setup CORS to allow Next.js frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Retriever (similar to the singleton in Streamlit app)
retriever = None

@app.on_event("startup")
async def startup_event():
    global retriever
    Base.metadata.create_all(bind=engine)
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
    sources = retriever.list_sources_by_type(user_id=current_user.id)
    return {"documents": sources["personal"], "global_documents": sources["global"]}

@app.post("/upload")
async def upload_document(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    
    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {SUPPORTED_EXTENSIONS}")
    
    # Read and check size
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File too large. Max allowed: {MAX_FILE_SIZE_MB} MB")
        
    save_path = UPLOAD_DIR / file.filename
    save_path.write_bytes(contents)
    
    try:
        import asyncio
        result = await asyncio.to_thread(retriever.ingest_file, save_path, current_user.id)
        return {"filename": file.filename, "chunks_added": result.chunks_added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents/{filename}")
def delete_document(filename: str, current_user: User = Depends(get_current_user)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    
    # Check ownership in ChromaDB before allowing deletion
    metadata = retriever._store._collection.get(where={"source": filename}, include=["metadatas"])
    
    is_global = False
    if metadata and metadata["metadatas"]:
        meta = metadata["metadatas"][0]
        is_global = meta.get("is_global") == 1
        owner_id = meta.get("user_id")
        
        if not is_global and owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this document.")
        if is_global and current_user.role not in ["admin", "editor"]:
            raise HTTPException(status_code=403, detail="Forbidden: You must be an admin or editor to delete a global document.")
    
    # Delete chunks
    if is_global or current_user.role in ["admin", "editor"]:
        retriever._store.delete_source(filename, user_id=None)
    else:
        retriever._store.delete_source(filename, user_id=current_user.id)
        
    # Delete physical file
    file_path = UPLOAD_DIR / filename
    file_deleted = False
    if file_path.exists():
        os.remove(file_path)
        file_deleted = True
        
    return {"status": "deleted", "filename": filename, "file_deleted": file_deleted}

@app.post("/sessions")
def create_session(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = ChatSession(title="New Chat", user_id=current_user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title}

@app.get("/sessions")
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sessions = db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.timestamp.asc()).all()
    return [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in messages]

@app.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Delete associated messages first
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"status": "deleted"}

@app.patch("/sessions/{session_id}")
def update_session(session_id: int, update: SessionTitleUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    session.title = update.title
    db.commit()
    return {"status": "updated", "title": session.title}

@app.post("/query")
def query_bot(request: QueryRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    session = db.query(ChatSession).filter(ChatSession.id == request.session_id, ChatSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = ChatMessage(session_id=request.session_id, role="user", content=request.query)
    db.add(user_msg)
    db.commit()

    # Route Query
    sources = retriever.list_sources(user_id=current_user.id)
    is_tabular, target_file = route_query(request.query, sources)
    
    if not target_file:
        query_lower = request.query.strip().lower()
        generic_words = ["summarize", "summarise", "summary", "give me a summary"]
        is_generic = query_lower in generic_words or query_lower.startswith("summarize ") or query_lower.startswith("summarise ")
        if is_generic:
            def generate_warning():
                warning_msg = "Please specify which document you would like me to summarize by tagging it with `!` (e.g., 'summarize !sample.txt')."
                yield warning_msg
                from src.database import SessionLocal
                with SessionLocal() as session:
                    bot_msg = ChatMessage(session_id=request.session_id, role="assistant", content=warning_msg)
                    session.add(bot_msg)
                    session.commit()
            return StreamingResponse(generate_warning(), media_type="text/plain")
    
    if is_tabular and target_file:
        # Generate tabular response
        def generate_tabular():
            from src.database import SessionLocal
            
            # Since Pandas agent doesn't stream token-by-token out of the box, we yield the whole thing
            response = run_tabular_query(request.query, target_file)
            yield response
            
            with SessionLocal() as session:
                bot_msg = ChatMessage(session_id=request.session_id, role="assistant", content=response)
                session.add(bot_msg)
                session.commit()
                
        return StreamingResponse(generate_tabular(), media_type="text/plain")

    # Fallback to standard semantic search
    chunks = retriever.retrieve(request.query, user_id=current_user.id, source_filter=target_file)
    
    def generate():
        from src.database import SessionLocal
        full_response = ""
        for chunk in stream_answer(request.query, chunks):
            full_response += chunk
            yield chunk
            
        with SessionLocal() as session:
            bot_msg = ChatMessage(session_id=request.session_id, role="assistant", content=full_response)
            session.add(bot_msg)
            session.commit()

    return StreamingResponse(generate(), media_type="text/plain")
