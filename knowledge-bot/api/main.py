from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
import os
from pathlib import Path
from sqlalchemy.orm import Session

from src.retrieval.retriever import Retriever
from src.generation.llm_chain import stream_answer
from src.config import UPLOAD_DIR, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS
from src.database import engine, Base, get_db
from src.models import ChatSession, ChatMessage

app = FastAPI(title="Enterprise Knowledge Bot API")

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

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/documents")
def list_documents():
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    sources = retriever.list_sources()
    return {"documents": sources}

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
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
        result = retriever.ingest_file(save_path)
        return {"filename": file.filename, "chunks_added": result.chunks_added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents/{filename}")
def delete_document(filename: str):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    success = retriever.delete_document(filename)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found or could not be deleted")
    return {"status": "deleted", "filename": filename}

@app.post("/sessions")
def create_session(db: Session = Depends(get_db)):
    session = ChatSession(title="New Chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "title": session.title}

@app.get("/sessions")
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]

@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: int, db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.timestamp.asc()).all()
    return [{"role": m.role, "content": m.content, "timestamp": m.timestamp} for m in messages]

@app.post("/query")
async def query_bot(request: QueryRequest, db: Session = Depends(get_db)):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    user_msg = ChatMessage(session_id=request.session_id, role="user", content=request.query)
    db.add(user_msg)
    db.commit()

    context, sources = retriever.retrieve(request.query)
    
    def generate():
        full_response = ""
        for chunk in stream_answer(request.query, context):
            full_response += chunk
            yield chunk
            
        bot_msg = ChatMessage(session_id=request.session_id, role="assistant", content=full_response)
        db.add(bot_msg)
        db.commit()

    return StreamingResponse(generate(), media_type="text/plain")
