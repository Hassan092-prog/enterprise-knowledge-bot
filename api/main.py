from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import shutil
import os
from pathlib import Path

from src.retrieval.retriever import Retriever
from src.generation.llm_chain import stream_answer
from src.config import UPLOAD_DIR, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS

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
    # Assuming config validation passes or we handle it
    retriever = Retriever()

class QueryRequest(BaseModel):
    query: str

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

@app.post("/query")
async def query_bot(request: QueryRequest):
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    # Get context from vector store
    context, sources = retriever.retrieve(request.query)
    
    def generate():
        for chunk in stream_answer(request.query, context):
            yield chunk
            
    # Include sources in headers so the frontend can parse them, or send a JSON payload via streaming
    # For simplicity, we just stream the text. The frontend might need a more complex streaming format
    # (e.g. SSE) to receive both text and citations. Here we use basic chunk streaming.
    return StreamingResponse(generate(), media_type="text/plain")
