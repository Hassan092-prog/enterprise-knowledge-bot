from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status, Request
from fastapi.responses import StreamingResponse
import csv
import io
import json
import re
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path

from src.models import (
    User, ChatSession, ChatMessage, AccessRequest, Tenant, ActivityLog, PendingTransfer,
    TenantSSOConfig
)
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
    SSO_ENTITY_ID,
    SSO_ACS_URL,
)
from src.database import generate_join_code
from src.activity import log_activity
from src.logger import get_logger
from api.limiter import limiter

logger = get_logger(__name__)
router = APIRouter()

# ──────────────────────────────────────────────────────────────────
# STATS & CORPUS MANAGEMENT (SCOPED TO TENANT)
# ──────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin_user)):
    from api.main import get_retriever
    r = get_retriever()
    tenant_id = current_user.tenant_id

    user_count = db.query(User).filter(User.tenant_id == tenant_id).count()
    session_count = db.query(ChatSession).filter(ChatSession.tenant_id == tenant_id).count()

    stats = r.get_knowledge_base_stats(user_id=None, tenant_id=tenant_id)

    return {
        "tenant_id": tenant_id,
        "tenant_name": current_user.tenant.name if current_user.tenant else None,
        "allowed_domains": current_user.tenant.allowed_domains if current_user.tenant else None,
        "users": user_count,
        "sessions": session_count,
        "total_chunks": stats["total_chunks"],
        "documents": stats["sources"],
    }

@router.post("/upload_global", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def upload_global_document(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_editor_user),
):
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
    try:
        save_path.write_bytes(contents)
    except Exception as io_err:
        logger.warning(f"Could not cache global file locally: {io_err}")

    from src.storage import get_storage_provider, get_object_key
    storage = get_storage_provider()
    storage_key = get_object_key(tenant_id=current_user.tenant_id, user_id=None, filename=clean_name, is_global=True)
    storage.upload_bytes(contents, storage_key)

    try:
        from src.worker import process_document
        task = process_document.delay(
            str(save_path),
            current_user.id,
            tenant_id=current_user.tenant_id,
            is_global=True,
            storage_key=storage_key,
        )

        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="DOC_UPLOAD",
            category="KNOWLEDGE",
            description=f"Queued company document '{clean_name}' for background ingestion (task={task.id})",
            details={"filename": clean_name, "is_global": True, "task_id": task.id, "storage_key": storage_key}
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

@router.delete("/documents_global/{filename}")
def delete_global_document(
    filename: str,
    current_user: User = Depends(get_current_editor_user),
):
    from api.main import get_retriever
    r = get_retriever()

    try:
        clean_name = sanitize_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    from src.storage import get_storage_provider, get_object_key
    storage = get_storage_provider()
    storage_key = get_object_key(tenant_id=current_user.tenant_id, user_id=None, filename=clean_name, is_global=True)
    file_path = get_tenant_upload_dir(current_user.tenant_id) / clean_name

    has_storage = storage.object_exists(storage_key)
    has_disk = file_path.exists()

    deleted_count = r.delete_document(
        clean_name,
        user_id=None,
        tenant_id=current_user.tenant_id,
    )

    if deleted_count == 0 and not has_storage and not has_disk:
        raise HTTPException(status_code=404, detail="Company document not found.")

    # Clean from object storage
    storage.delete_object(storage_key)

    # Clean from tenant directory if present
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception:
            pass

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

@router.delete("/users/{user_id}")
def remove_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    target_user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id
    ).first()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found in your organization")

    if target_user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove your own account")

    if target_user.role == "superadmin":
        raise HTTPException(status_code=403, detail="Cannot remove the organization SuperAdmin")

    if current_user.role != "superadmin" and target_user.role in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Admins cannot remove fellow Admins")

    username = target_user.username

    # Clean up user's private chat sessions and messages
    sessions = db.query(ChatSession).filter(ChatSession.user_id == target_user.id).all()
    for s in sessions:
        db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
        db.delete(s)

    # Clean up pending access requests and transfers
    db.query(AccessRequest).filter(AccessRequest.user_id == target_user.id).delete()
    db.query(PendingTransfer).filter(
        (PendingTransfer.to_user_id == target_user.id) | (PendingTransfer.from_user_id == target_user.id)
    ).delete()

    # Purge offboarded member's personal documents from ChromaDB and storage
    try:
        from src.retrieval.vector_store import VectorStore
        from src.storage import get_storage_provider
        vs = VectorStore()
        vs.delete_all_user_personal_chunks(user_id=target_user.id, tenant_id=current_user.tenant_id)
        storage = get_storage_provider()
        prefix = f"tenants/{current_user.tenant_id}/personal/{target_user.id}/"
        for obj_key in storage.list_objects(prefix=prefix):
            storage.delete_object(obj_key)
    except Exception as cleanup_err:
        logger.warning(f"Notice purging personal documents for offboarded user {target_user.id}: {cleanup_err}")

    db.delete(target_user)
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="USER_REMOVED",
        category="GOVERNANCE",
        description=f"Removed member '{username}' from the organization",
        details={"removed_user": username}
    )

    return {"status": "success", "message": f"User {username} successfully removed"}


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

@router.post("/cancel_transfer/{transfer_id}")
def cancel_superadmin_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superadmin_user),
):
    transfer = db.query(PendingTransfer).filter(
        PendingTransfer.id == transfer_id,
        PendingTransfer.tenant_id == current_user.tenant_id,
        PendingTransfer.from_user_id == current_user.id,
        PendingTransfer.status == "pending"
    ).first()

    if not transfer:
        raise HTTPException(status_code=404, detail="Pending transfer not found or already processed")

    transfer.status = "cancelled"
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="SUPERADMIN_TRANSFER_CANCELLED",
        category="GOVERNANCE",
        description=f"Cancelled SuperAdmin ownership transfer to '{transfer.to_user.username if transfer.to_user else 'user'}'",
        details={"transfer_id": transfer.id}
    )

    return {"status": "success", "message": "Ownership transfer cancelled"}

@router.post("/reject_transfer/{transfer_id}")
def reject_superadmin_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(PendingTransfer).filter(
        PendingTransfer.id == transfer_id,
        PendingTransfer.tenant_id == current_user.tenant_id,
        PendingTransfer.to_user_id == current_user.id,
        PendingTransfer.status == "pending"
    ).first()

    if not transfer:
        raise HTTPException(status_code=404, detail="Pending transfer not found or already processed")

    transfer.status = "rejected"
    db.commit()

    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="SUPERADMIN_TRANSFER_REJECTED",
        category="GOVERNANCE",
        description=f"Declined SuperAdmin ownership transfer",
        details={"transfer_id": transfer.id}
    )

    return {"status": "success", "message": "Ownership transfer declined"}


# ──────────────────────────────────────────────────────────────────
# ACTIVITY AUDIT LOG (TENANT-SCOPED)
# ──────────────────────────────────────────────────────────────────

def _filter_activity_query(
    db: Session,
    tenant_id: int,
    category: Optional[str] = None,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    query = db.query(ActivityLog).filter(ActivityLog.tenant_id == tenant_id)
    if category and category.upper() != "ALL":
        query = query.filter(ActivityLog.category == category.upper())
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    if search and search.strip():
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            (ActivityLog.description.ilike(search_pattern)) |
            (ActivityLog.action.ilike(search_pattern))
        )
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query = query.filter(ActivityLog.timestamp >= start_dt)
        except Exception:
            pass
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query = query.filter(ActivityLog.timestamp <= end_dt)
        except Exception:
            pass
    return query

@router.get("/activity")
def get_tenant_activity(
    category: Optional[str] = None,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    base_query = _filter_activity_query(
        db=db,
        tenant_id=current_user.tenant_id,
        category=category,
        user_id=user_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )
    total_count = base_query.count()
    logs = base_query.order_by(ActivityLog.timestamp.desc()).offset(offset).limit(limit).all()

    return {
        "total": total_count,
        "offset": offset,
        "limit": limit,
        "logs": [{
            "id": log.id,
            "user_id": log.user_id,
            "username": log.user.username if log.user else "System",
            "action": log.action,
            "category": log.category,
            "description": log.description,
            "details": log.details,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None
        } for log in logs]
    }

def _sanitize_csv_cell(val: any) -> str:
    """
    Prevents CSV Formula Injection (CWE-1236).
    Prepends a single quote to prevent spreadsheet apps from executing formulas
    if the value starts with =, +, -, @, tab, or carriage return (including leading whitespace).
    """
    if val is None:
        return ""
    s = str(val)
    stripped = s.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s

def _parse_details_safe(details_raw: any):
    if not details_raw:
        return None
    if isinstance(details_raw, (dict, list)):
        return details_raw
    s = str(details_raw).strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            return s
    return s

@router.get("/activity/export")
def export_tenant_activity(
    format: str = Query("csv", pattern="^(csv|json)$"),
    category: Optional[str] = None,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """
    Export tamper-evident tenant audit trail in CSV or JSON format for compliance audits.
    """
    base_query = _filter_activity_query(
        db=db,
        tenant_id=current_user.tenant_id,
        category=category,
        user_id=user_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
    )
    logs = base_query.order_by(ActivityLog.timestamp.desc()).all()

    tenant_name = current_user.tenant.name if current_user.tenant else f"tenant_{current_user.tenant_id}"
    tenant_slug = re.sub(r'[^a-zA-Z0-9_]', '_', tenant_name.lower())
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")

    # Record the export event itself in the audit trail
    log_activity(
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="AUDIT_EXPORT",
        category="GOVERNANCE",
        description=f"Exported {len(logs)} audit log records in {format.upper()} format",
        details={"record_count": len(logs), "format": format, "category": category}
    )

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Log ID", "Timestamp (UTC)", "User ID", "Username", "Category", "Action", "Description", "Details (JSON)"])
        for l in logs:
            writer.writerow([
                l.id,
                l.timestamp.isoformat() if l.timestamp else "",
                l.user_id or "",
                _sanitize_csv_cell(l.user.username if l.user else "System"),
                _sanitize_csv_cell(l.category),
                _sanitize_csv_cell(l.action),
                _sanitize_csv_cell(l.description),
                _sanitize_csv_cell(l.details or "")
            ])
        output.seek(0)
        filename = f"audit_log_{tenant_slug}_{timestamp_str}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    else:
        data = [{
            "id": l.id,
            "tenant_id": l.tenant_id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "user_id": l.user_id,
            "username": l.user.username if l.user else "System",
            "category": l.category,
            "action": l.action,
            "description": l.description,
            "details": _parse_details_safe(l.details)
        } for l in logs]
        filename = f"audit_log_{tenant_slug}_{timestamp_str}.json"
        json_content = json.dumps(data, indent=2)
        return StreamingResponse(
            iter([json_content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )


# ──────────────────────────────────────────────────────────────────
# ENTERPRISE SSO & DIRECTORY SYNC CONFIGURATION (PHASE 12)
# ──────────────────────────────────────────────────────────────────

class TenantSSOConfigRequest(BaseModel):
    idp_type: str = "saml"  # 'saml', 'oidc', 'okta', 'google', 'microsoft'
    is_enabled: bool = True
    enforce_sso: bool = False
    idp_entity_id: Optional[str] = None
    idp_sso_url: Optional[str] = None
    idp_x509_cert: Optional[str] = None
    idp_metadata_xml: Optional[str] = None
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_scopes: Optional[str] = "openid email profile groups"
    allowed_domains: Optional[str] = None
    default_role: str = "user"
    role_mapping_json: Optional[str] = None


@router.get("/sso/config")
def get_tenant_sso_config(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Returns SSO & Directory Sync settings for the current tenant organization."""
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == tenant_id).first()
    sp_meta_url = SSO_ENTITY_ID if "/auth/sso/saml/metadata" in SSO_ENTITY_ID else f"{SSO_ENTITY_ID.rstrip('/')}/auth/sso/saml/metadata"
    if not cfg:
        return {
            "configured": False,
            "tenant_id": tenant_id,
            "idp_type": "saml",
            "is_enabled": False,
            "enforce_sso": False,
            "default_role": "user",
            "sp_entity_id": SSO_ENTITY_ID,
            "sp_acs_url": SSO_ACS_URL,
            "sp_metadata_url": sp_meta_url,
        }

    return {
        "configured": True,
        "tenant_id": cfg.tenant_id,
        "idp_type": cfg.idp_type,
        "is_enabled": cfg.is_enabled,
        "enforce_sso": cfg.enforce_sso,
        "idp_entity_id": cfg.idp_entity_id,
        "idp_sso_url": cfg.idp_sso_url,
        "idp_x509_cert": cfg.idp_x509_cert,
        "has_metadata_xml": bool(cfg.idp_metadata_xml),
        "oidc_issuer_url": cfg.oidc_issuer_url,
        "oidc_client_id": cfg.oidc_client_id,
        "oidc_has_secret": bool(cfg.oidc_client_secret),
        "oidc_scopes": cfg.oidc_scopes,
        "allowed_domains": cfg.allowed_domains,
        "default_role": cfg.default_role,
        "role_mapping_json": cfg.role_mapping_json,
        "sp_entity_id": SSO_ENTITY_ID,
        "sp_acs_url": SSO_ACS_URL,
        "sp_metadata_url": sp_meta_url,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@router.post("/sso/config")
def upsert_tenant_sso_config(
    payload: TenantSSOConfigRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Configures or updates enterprise SAML 2.0 or OIDC Identity Provider parameters.
    Auto-parses raw metadata XML if provided.
    """
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context required")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Organization not found")

    valid_idp_types = {"saml", "oidc", "okta", "google", "microsoft"}
    clean_idp_type = (payload.idp_type or "saml").lower().strip()
    if clean_idp_type not in valid_idp_types:
        raise HTTPException(status_code=400, detail=f"Invalid idp_type '{payload.idp_type}'. Must be one of: {', '.join(valid_idp_types)}")

    clean_default_role = (payload.default_role or "user").lower().strip()
    if clean_default_role not in ("user", "editor", "admin"):
        raise HTTPException(status_code=400, detail=f"Invalid default_role '{payload.default_role}'. Must be user, editor, or admin.")

    # Validate allowed_domains against public mail providers and syntax
    clean_domains_list = []
    if payload.allowed_domains and payload.allowed_domains.strip():
        from src.sso import PUBLIC_EMAIL_DOMAINS
        for d in payload.allowed_domains.split(","):
            cd = d.strip().lower().rstrip(".")
            if not cd:
                continue
            if cd in PUBLIC_EMAIL_DOMAINS:
                raise HTTPException(status_code=400, detail=f"Public domain '{cd}' cannot be configured for corporate SSO auto-routing.")
            if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", cd):
                raise HTTPException(status_code=400, detail=f"Invalid corporate domain format: '{cd}'")
            clean_domains_list.append(cd)
    clean_allowed_domains = ", ".join(clean_domains_list) if clean_domains_list else None

    # If raw metadata XML was supplied, parse fields automatically
    parsed_metadata = {}
    if payload.idp_metadata_xml and payload.idp_metadata_xml.strip():
        from src.sso.saml import parse_idp_metadata_xml
        try:
            parsed_metadata = parse_idp_metadata_xml(payload.idp_metadata_xml)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse IdP metadata XML: {str(e)}")

    idp_entity_id = parsed_metadata.get("idp_entity_id") or payload.idp_entity_id
    idp_sso_url = parsed_metadata.get("idp_sso_url") or payload.idp_sso_url
    idp_x509_cert = parsed_metadata.get("idp_x509_cert") or payload.idp_x509_cert

    # Validate role mapping JSON if given
    if payload.role_mapping_json and payload.role_mapping_json.strip():
        try:
            parsed_rm = json.loads(payload.role_mapping_json)
            if not isinstance(parsed_rm, dict):
                raise ValueError("Role mapping must be a JSON object mapping group names to roles")
            valid_roles = {"user", "editor", "admin"}
            for g, r in parsed_rm.items():
                if r not in valid_roles:
                    raise ValueError(f"Invalid target role '{r}' for group '{g}'. Must be user, editor, or admin.")
        except Exception as err:
            raise HTTPException(status_code=400, detail=f"Invalid role_mapping_json: {str(err)}")

    cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == tenant_id).first()
    if cfg:
        cfg.idp_type = clean_idp_type
        cfg.is_enabled = payload.is_enabled
        cfg.enforce_sso = payload.enforce_sso
        cfg.idp_entity_id = idp_entity_id
        cfg.idp_sso_url = idp_sso_url
        cfg.idp_x509_cert = idp_x509_cert
        if payload.idp_metadata_xml:
            cfg.idp_metadata_xml = payload.idp_metadata_xml
        cfg.oidc_issuer_url = payload.oidc_issuer_url
        cfg.oidc_client_id = payload.oidc_client_id
        if payload.oidc_client_secret:
            cfg.oidc_client_secret = payload.oidc_client_secret
        cfg.oidc_scopes = payload.oidc_scopes or "openid email profile groups"
        cfg.allowed_domains = clean_allowed_domains
        cfg.default_role = clean_default_role
        cfg.role_mapping_json = payload.role_mapping_json
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = TenantSSOConfig(
            tenant_id=tenant_id,
            idp_type=clean_idp_type,
            is_enabled=payload.is_enabled,
            enforce_sso=payload.enforce_sso,
            idp_entity_id=idp_entity_id,
            idp_sso_url=idp_sso_url,
            idp_x509_cert=idp_x509_cert,
            idp_metadata_xml=payload.idp_metadata_xml,
            oidc_issuer_url=payload.oidc_issuer_url,
            oidc_client_id=payload.oidc_client_id,
            oidc_client_secret=payload.oidc_client_secret,
            oidc_scopes=payload.oidc_scopes or "openid email profile groups",
            allowed_domains=clean_allowed_domains,
            default_role=clean_default_role,
            role_mapping_json=payload.role_mapping_json,
        )
        db.add(cfg)

    # Sync allowed_domains to Tenant model
    if clean_allowed_domains:
        tenant.allowed_domains = clean_allowed_domains

    db.commit()
    db.refresh(cfg)

    log_activity(
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="SSO_CONFIG_UPDATED",
        category="GOVERNANCE",
        description=f"Updated Enterprise SSO configuration ({cfg.idp_type.upper()}, enabled={cfg.is_enabled})",
        details={
            "idp_type": cfg.idp_type,
            "is_enabled": cfg.is_enabled,
            "enforce_sso": cfg.enforce_sso,
            "allowed_domains": cfg.allowed_domains
        }
    )

    return {
        "status": "success",
        "message": "Enterprise SSO configuration saved.",
        "configured": True,
        "tenant_id": cfg.tenant_id,
        "idp_type": cfg.idp_type,
        "is_enabled": cfg.is_enabled,
        "enforce_sso": cfg.enforce_sso,
        "idp_entity_id": cfg.idp_entity_id,
        "idp_sso_url": cfg.idp_sso_url,
        "idp_x509_cert": cfg.idp_x509_cert,
        "has_metadata_xml": bool(cfg.idp_metadata_xml),
        "oidc_issuer_url": cfg.oidc_issuer_url,
        "oidc_client_id": cfg.oidc_client_id,
        "oidc_has_secret": bool(cfg.oidc_client_secret),
        "oidc_scopes": cfg.oidc_scopes,
        "allowed_domains": cfg.allowed_domains,
        "default_role": cfg.default_role,
        "role_mapping_json": cfg.role_mapping_json,
        "sp_entity_id": SSO_ENTITY_ID,
        "sp_acs_url": SSO_ACS_URL,
        "sp_metadata_url": SSO_ENTITY_ID if "/auth/sso/saml/metadata" in SSO_ENTITY_ID else f"{SSO_ENTITY_ID.rstrip('/')}/auth/sso/saml/metadata",
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@router.delete("/sso/config")
def delete_tenant_sso_config(
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """Disables and removes Enterprise SSO configuration for the current tenant."""
    tenant_id = current_user.tenant_id
    cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == tenant_id).first()
    if not cfg:
        raise HTTPException(status_code=404, detail="No SSO configuration found for this organization")

    db.delete(cfg)
    db.commit()

    log_activity(
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="SSO_CONFIG_DELETED",
        category="GOVERNANCE",
        description="Removed Enterprise SSO configuration",
    )

    return {"status": "success", "message": "Enterprise SSO configuration removed."}
