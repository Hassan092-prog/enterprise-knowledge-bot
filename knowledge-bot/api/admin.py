from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path

from src.models import User, ChatSession, ChatMessage, AccessRequest
from api.dependencies import get_db, get_current_admin_user, get_current_editor_user
from src.config import UPLOAD_DIR, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS


router = APIRouter()

@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    from api.main import retriever
    user_count = db.query(User).count()
    session_count = db.query(ChatSession).count()
    
    # We pass user_id=None to get stats of all global documents if needed, but VectorStore 
    # currently requires a user_id or it returns everything. Let's just return total chunks.
    stats = retriever.get_knowledge_base_stats(user_id=None)
    
    return {
        "users": user_count,
        "sessions": session_count,
        "total_chunks": stats["total_chunks"],
        "documents": stats["sources"]
    }

@router.post("/upload_global")
async def upload_global_document(file: UploadFile = File(...), current_user: User = Depends(get_current_editor_user)):
    from api.main import retriever
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
        # Ingest as global document (no specific user_id required, is_global=True)
        result = retriever.ingest_file(save_path, user_id=None, is_global=True)
        return {"filename": file.filename, "chunks_added": result.chunks_added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents_global/{filename}")
def delete_global_document(filename: str, current_user: User = Depends(get_current_editor_user)):
    from api.main import retriever
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")
    # Delete global document by passing user_id=None
    success = retriever.delete_document(filename, user_id=None)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found or could not be deleted")
    return {"status": "deleted", "filename": filename}

class RoleChangeRequest(BaseModel):
    role: str

@router.post("/users/{user_id}/role")
def change_user_role(user_id: int, role_req: RoleChangeRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    if role_req.role not in ["user", "editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.role = role_req.role
    db.commit()
    return {"status": "success", "message": f"User {user.username} role changed to {role_req.role}"}

@router.post("/make_me_admin")
def make_me_admin(db: Session = Depends(get_db)):
    """Secret endpoint to bootstrap the first admin."""
    # We just make the first user an admin
    user = db.query(User).first()
    if user:
        user.role = "admin"
        db.commit()
        return {"status": "success"}
    return {"status": "failed", "detail": "No users exist yet"}

@router.get("/requests")
def get_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    requests = db.query(AccessRequest).filter(AccessRequest.status == "pending").all()
    return [{
        "id": req.id,
        "user_id": req.user_id,
        "username": req.user.username,
        "requested_role": req.requested_role,
        "created_at": req.created_at
    } for req in requests]

@router.post("/requests/{request_id}/approve")
def approve_request(request_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    
    req.status = "approved"
    req.user.role = req.requested_role
    db.commit()
    return {"status": "success"}

@router.post("/requests/{request_id}/reject")
def reject_request(request_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    
    req.status = "rejected"
    db.commit()
    return {"status": "success"}

@router.get("/users")
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    users = db.query(User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "created_at": u.created_at
    } for u in users]
