from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path

from src.models import User, ChatSession, ChatMessage, AccessRequest, Tenant, ActivityLog, PendingTransfer
from api.dependencies import (
    get_db,
    get_current_user,
    get_current_admin_user,
    get_current_editor_user,
    get_current_superadmin_user,
)
from src.config import (
    MAX_FILE_SIZE_MB,
    SUPPORTED_EXTENSIONS,
    sanitize_filename,
    get_tenant_upload_dir,
)
from src.database import generate_join_code
from src.activity import log_activity

router = APIRouter()

# ──────────────────────────────────────────────────────────────────
# STATS & CORPUS MANAGEMENT (SCOPED TO TENANT)
# ──────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    from api.main import retriever
    tenant_id = current_user.tenant_id

    user_count = db.query(User).filter(User.tenant_id == tenant_id).count()
    session_count = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()

    stats = retriever.get_knowledge_base_stats(user_id=None, tenant_id=tenant_id)

    return {
        "tenant_id": tenant_id,
        "tenant_name": current_user.tenant.name if current_user.tenant else None,
        "users": user_count,
        "sessions": session_count,
        "total_chunks": stats["total_chunks"],
        "documents": stats["sources"],
    }

@router.post("/upload_global")
async def upload_global_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_editor_user),
):
    from api.main import retriever
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

    try:
        clean_name = sanitize_filename(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ext = Path(clean_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Supported: {SUPPORTED_EXTENSIONS}")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"File too large. Max allowed: {MAX_FILE_SIZE_MB} MB")

    tenant_dir = get_tenant_upload_dir(current_user.tenant_id)
    save_path = tenant_dir / clean_name
    save_path.write_bytes(contents)

    try:
        result = retriever.ingest_file(
            save_path,
            user_id=None,
            is_global=True,
            tenant_id=current_user.tenant_id,
        )
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="DOC_UPLOAD",
            category="KNOWLEDGE",
            description=f"Uploaded company document '{clean_name}' ({result.chunks_added} chunks)",
            details={"filename": clean_name, "chunks_added": result.chunks_added, "is_global": True}
        )
        return {"filename": clean_name, "chunks_added": result.chunks_added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents_global/{filename}")
def delete_global_document(
    filename: str,
    current_user: User = Depends(get_current_editor_user),
):
    from api.main import retriever
    if not retriever:
        raise HTTPException(status_code=500, detail="Retriever not initialized")

    try:
        clean_name = sanitize_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    deleted_count = retriever.delete_document(
        clean_name,
        user_id=None,
        tenant_id=current_user.tenant_id,
    )

    # Clean from tenant directory if present
    file_path = get_tenant_upload_dir(current_user.tenant_id) / clean_name
    if file_path.exists():
        file_path.unlink()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="DOC_DELETE",
        category="KNOWLEDGE",
        description=f"Deleted company document '{clean_name}' ({deleted_count} chunks purged)",
        details={"filename": clean_name, "chunks_deleted": deleted_count}
    )

    return {"status": "deleted", "filename": clean_name, "chunks_deleted": deleted_count}


# ──────────────────────────────────────────────────────────────────
# USER MANAGEMENT & ROLES
# ──────────────────────────────────────────────────────────────────

class RoleChangeRequest(BaseModel):
    role: str

@router.get("/users")
def get_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    users = db.query(User).filter(User.tenant_id == current_user.tenant_id).all()
    return [{
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "is_platform_admin": u.is_platform_admin,
        "created_at": u.created_at
    } for u in users]

@router.post("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    role_req: RoleChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    if role_req.role not in ["user", "editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role. SuperAdmin must be assigned via ownership transfer.")

    target_user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found in your organization")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot alter your own role")

    # If current user is standard Admin (not SuperAdmin)
    if current_user.role != "superadmin":
        if target_user.role in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Admins cannot modify fellow Admins or SuperAdmin")
        if role_req.role == "admin":
            raise HTTPException(status_code=403, detail="Only SuperAdmin can promote users to Admin")

    old_role = target_user.role
    target_user.role = role_req.role
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="ROLE_CHANGE",
        category="GOVERNANCE",
        description=f"Changed '{target_user.username}' role from '{old_role}' to '{role_req.role}'",
        details={"target_user": target_user.username, "old_role": old_role, "new_role": role_req.role}
    )

    return {"status": "success", "message": f"User {target_user.username} role changed to {role_req.role}"}


# ──────────────────────────────────────────────────────────────────
# ACCESS REQUESTS (ROLE PROMOTION)
# ──────────────────────────────────────────────────────────────────

@router.get("/requests")
def get_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    requests = db.query(AccessRequest).filter(
        AccessRequest.tenant_id == current_user.tenant_id,
        AccessRequest.status == "pending"
    ).all()
    return [{
        "id": req.id,
        "user_id": req.user_id,
        "username": req.user.username,
        "requested_role": req.requested_role,
        "created_at": req.created_at
    } for req in requests]

@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    req = db.query(AccessRequest).filter(
        AccessRequest.id == request_id,
        AccessRequest.tenant_id == current_user.tenant_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.requested_role == "admin" and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can approve Admin promotions")

    req.status = "approved"
    target_user = req.user
    old_role = target_user.role
    target_user.role = req.requested_role
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="ROLE_CHANGE",
        category="GOVERNANCE",
        description=f"Approved promotion of '{target_user.username}' from '{old_role}' to '{req.requested_role}'",
        details={"target_user": target_user.username, "old_role": old_role, "new_role": req.requested_role}
    )

    return {"status": "success"}

@router.post("/requests/{request_id}/reject")
def reject_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    req = db.query(AccessRequest).filter(
        AccessRequest.id == request_id,
        AccessRequest.tenant_id == current_user.tenant_id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    req.status = "rejected"
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="ROLE_REQUEST_REJECTED",
        category="GOVERNANCE",
        description=f"Rejected role request for '{req.user.username}' ({req.requested_role})"
    )

    return {"status": "success"}


# ──────────────────────────────────────────────────────────────────
# JOIN CODE MANAGEMENT
# ──────────────────────────────────────────────────────────────────

@router.get("/join_code")
def get_join_code(current_user: User = Depends(get_current_admin_user)):
    tenant = current_user.tenant
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant organization not found")
    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "join_code": tenant.join_code
    }

@router.post("/regenerate_join_code")
def regenerate_join_code(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superadmin_user),
):
    tenant = current_user.tenant
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant organization not found")

    old_code = tenant.join_code
    new_code = generate_join_code()
    tenant.join_code = new_code
    db.commit()

    log_activity(
        tenant_id=tenant.id,
        user_id=current_user.id,
        action="JOIN_CODE_REGENERATED",
        category="GOVERNANCE",
        description="Regenerated company registration join code",
        details={"old_code": old_code, "new_code": new_code}
    )

    return {"status": "success", "join_code": new_code}


# ──────────────────────────────────────────────────────────────────
# SUPERADMIN OWNERSHIP TRANSFER (2-STEP HANDSHAKE)
# ──────────────────────────────────────────────────────────────────

class TransferRequest(BaseModel):
    to_user_id: int

@router.post("/transfer_superadmin")
def initiate_superadmin_transfer(
    transfer_req: TransferRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superadmin_user),
):
    if transfer_req.to_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot transfer ownership to yourself")

    target_user = db.query(User).filter(
        User.id == transfer_req.to_user_id,
        User.tenant_id == current_user.tenant_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found in your organization")

    # Invalidate any existing pending transfers
    existing_transfers = db.query(PendingTransfer).filter(
        PendingTransfer.tenant_id == current_user.tenant_id,
        PendingTransfer.status == "pending"
    ).all()
    for et in existing_transfers:
        et.status = "cancelled"

    transfer = PendingTransfer(
        tenant_id=current_user.tenant_id,
        from_user_id=current_user.id,
        to_user_id=target_user.id,
        status="pending",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=24)
    )
    db.add(transfer)
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="SUPERADMIN_TRANSFER_INITIATED",
        category="GOVERNANCE",
        description=f"Initiated SuperAdmin transfer to '{target_user.username}' (expires in 24 hours)",
        details={"to_user": target_user.username, "transfer_id": transfer.id}
    )

    return {
        "status": "initiated",
        "transfer_id": transfer.id,
        "to_username": target_user.username,
        "expires_at": transfer.expires_at
    }

@router.get("/pending_transfers")
def get_pending_transfers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Retrieve transfers where user is either sender or receiver
    now = datetime.utcnow()
    transfers = db.query(PendingTransfer).filter(
        PendingTransfer.tenant_id == current_user.tenant_id,
        PendingTransfer.status == "pending",
        PendingTransfer.expires_at > now
    ).all()

    return [{
        "id": t.id,
        "from_user_id": t.from_user_id,
        "from_username": t.from_user.username if t.from_user else None,
        "to_user_id": t.to_user_id,
        "to_username": t.to_user.username if t.to_user else None,
        "created_at": t.created_at,
        "expires_at": t.expires_at,
        "is_recipient": (t.to_user_id == current_user.id)
    } for t in transfers]

@router.post("/accept_transfer/{transfer_id}")
def accept_superadmin_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(PendingTransfer).filter(
        PendingTransfer.id == transfer_id,
        PendingTransfer.tenant_id == current_user.tenant_id,
        PendingTransfer.status == "pending"
    ).first()

    if not transfer:
        raise HTTPException(status_code=404, detail="Pending transfer not found or already processed")

    if transfer.to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not the designated recipient of this transfer")

    if datetime.utcnow() > transfer.expires_at:
        transfer.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Transfer offer has expired")

    from_user = db.query(User).filter(User.id == transfer.from_user_id).first()
    tenant = current_user.tenant

    # Handshake execution:
    # 1. Promote recipient to SuperAdmin
    current_user.role = "superadmin"
    # 2. Demote previous SuperAdmin to Admin
    if from_user:
        from_user.role = "admin"
    # 3. Update tenant pointer
    if tenant:
        tenant.superadmin_user_id = current_user.id

    transfer.status = "accepted"
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="SUPERADMIN_TRANSFER_ACCEPTED",
        category="GOVERNANCE",
        description=f"Accepted SuperAdmin ownership transfer from '{from_user.username if from_user else 'former superadmin'}'",
        details={"new_superadmin": current_user.username, "previous_superadmin": from_user.username if from_user else None}
    )

    return {"status": "success", "message": "SuperAdmin ownership transferred successfully"}


# ──────────────────────────────────────────────────────────────────
# ACTIVITY AUDIT LOG (TENANT-SCOPED)
# ──────────────────────────────────────────────────────────────────

@router.get("/activity")
def get_tenant_activity(
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    query = db.query(ActivityLog).filter(ActivityLog.tenant_id == current_user.tenant_id)
    if category:
        query = query.filter(ActivityLog.category == category.upper())

    logs = query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()

    return [{
        "id": log.id,
        "user_id": log.user_id,
        "username": log.user.username if log.user else "System",
        "action": log.action,
        "category": log.category,
        "description": log.description,
        "details": log.details,
        "timestamp": log.timestamp
    } for log in logs]
