import shutil
import io
import csv
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.models import Tenant, User, ChatSession, ActivityLog
from api.dependencies import get_db, get_current_platform_admin
from src.config import get_tenant_upload_dir, UPLOAD_DIR
from src.logger import get_logger
from api.limiter import limiter, get_user_rate_limit_key

logger = get_logger(__name__)

router = APIRouter()

# ──────────────────────────────────────────────────────────────────
# PLATFORM GLOBAL STATS & OVERVIEW
# ──────────────────────────────────────────────────────────────────

@router.get("/stats")
@limiter.limit("60/minute", key_func=get_user_rate_limit_key)
def get_platform_global_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    from api.main import get_retriever

    total_tenants = db.query(Tenant).count()
    active_tenants = db.query(Tenant).filter(Tenant.status == "active").count()
    total_users = db.query(User).count()
    total_queries = db.query(ActivityLog).filter(ActivityLog.category == "QUERY").count()

    total_chunks = 0
    r = get_retriever()
    if r and r._store:
        total_chunks = r._store.get_stats().get("total_chunks", 0)

    return {
        "total_tenants": total_tenants,
        "active_tenants": active_tenants,
        "total_users": total_users,
        "total_queries": total_queries,
        "total_chunks": total_chunks,
    }

# ──────────────────────────────────────────────────────────────────
# TENANT DIRECTORY & MANAGEMENT
# ──────────────────────────────────────────────────────────────────

@router.get("/tenants")
@limiter.limit("60/minute", key_func=get_user_rate_limit_key)
def list_all_tenants(
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    from api.main import get_retriever

    r = get_retriever()
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    results = []

    for t in tenants:
        member_count = db.query(User).filter(User.tenant_id == t.id).count()
        owner = db.query(User).filter(User.id == t.superadmin_user_id).first() if t.superadmin_user_id else None

        doc_count = 0
        chunk_count = 0
        if r and r._store:
            t_stats = r.get_knowledge_base_stats(user_id=None, tenant_id=t.id)
            doc_count = t_stats.get("total_sources", 0)
            chunk_count = t_stats.get("total_chunks", 0)

        results.append({
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "status": t.status,
            "join_code": t.join_code,
            "created_at": t.created_at,
            "owner": owner.username if owner else "Unassigned",
            "member_count": member_count,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
            "monthly_token_budget": t.monthly_token_budget if t.monthly_token_budget is not None else 500000,
            "current_month_tokens": t.current_month_tokens if t.current_month_tokens is not None else 0,
            "budget_reset_at": t.budget_reset_at,
        })

    return results

@router.get("/tenants/{tenant_id}")
@limiter.limit("60/minute", key_func=get_user_rate_limit_key)
def inspect_tenant(
    request: Request,
    tenant_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    from api.main import get_retriever

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant organization not found")

    users = db.query(User).filter(User.tenant_id == tenant_id).all()
    recent_activity = db.query(ActivityLog).filter(
        ActivityLog.tenant_id == tenant_id
    ).order_by(ActivityLog.timestamp.desc()).limit(20).all()

    sources = {"personal": [], "global": []}
    r = get_retriever()
    if r:
        sources = r.list_sources_by_type(user_id=None, tenant_id=tenant_id)

    return {
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "join_code": tenant.join_code,
            "created_at": tenant.created_at,
            "monthly_token_budget": tenant.monthly_token_budget if tenant.monthly_token_budget is not None else 500000,
            "current_month_tokens": tenant.current_month_tokens if tenant.current_month_tokens is not None else 0,
            "budget_reset_at": tenant.budget_reset_at,
        },
        "members": [{
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at
        } for u in users],
        "documents": sources,
        "recent_activity": [{
            "id": a.id,
            "username": a.user.username if a.user else "System",
            "action": a.action,
            "category": a.category,
            "description": a.description,
            "timestamp": a.timestamp
        } for a in recent_activity]
    }

class TenantBudgetUpdate(BaseModel):
    monthly_token_budget: Optional[int] = None
    reset_usage: bool = False

@router.patch("/tenants/{tenant_id}/budget")
@limiter.limit("10/minute", key_func=get_user_rate_limit_key)
def update_tenant_budget(
    request: Request,
    tenant_id: int,
    budget_data: TenantBudgetUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant organization not found")

    if budget_data.monthly_token_budget is not None:
        if budget_data.monthly_token_budget < 0:
            raise HTTPException(status_code=400, detail="Token budget cannot be negative")
        tenant.monthly_token_budget = budget_data.monthly_token_budget

    if budget_data.reset_usage:
        tenant.current_month_tokens = 0
        tenant.budget_reset_at = datetime.utcnow()

    db.commit()
    db.refresh(tenant)

    return {
        "status": "success",
        "tenant_id": tenant.id,
        "monthly_token_budget": tenant.monthly_token_budget,
        "current_month_tokens": tenant.current_month_tokens,
        "budget_reset_at": tenant.budget_reset_at,
    }

@router.get("/export/csv")
@limiter.limit("60/minute", key_func=get_user_rate_limit_key)
def export_tenants_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    from api.admin import _sanitize_csv_cell

    tenants = db.query(Tenant).order_by(Tenant.id.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Tenant ID",
        "Organization Name",
        "Slug",
        "Status",
        "Monthly Token Budget",
        "Current Month Tokens",
        "Usage Percent",
        "Reset Date",
        "Created At"
    ])

    for t in tenants:
        budget = t.monthly_token_budget if t.monthly_token_budget is not None else 500000
        used = t.current_month_tokens if t.current_month_tokens is not None else 0
        pct = round((used / budget * 100), 2) if budget > 0 else 0.0
        reset_str = t.budget_reset_at.strftime("%Y-%m-%d %H:%M:%S") if t.budget_reset_at else "N/A"
        created_str = t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else "N/A"
        writer.writerow([
            t.id,
            _sanitize_csv_cell(t.name),
            _sanitize_csv_cell(t.slug),
            _sanitize_csv_cell(t.status),
            budget,
            used,
            f"{pct}%",
            reset_str,
            created_str
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=tenants_usage_report_{datetime.utcnow().strftime('%Y%m%d')}.csv"}
    )

class TenantStatusUpdate(BaseModel):
    status: str

@router.post("/tenants/{tenant_id}/status")
@limiter.limit("10/minute", key_func=get_user_rate_limit_key)
def update_tenant_status(
    request: Request,
    tenant_id: int,
    status_data: TenantStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    if status_data.status not in ["active", "suspended"]:
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'suspended'")

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    old_status = tenant.status
    tenant.status = status_data.status
    db.commit()

    if status_data.status == "suspended":
        try:
            from src.sso.revocation import revoke_tenant_sessions
            revoke_tenant_sessions(tenant_id)
        except Exception as rev_err:
            logger.warning(f"Failed to revoke Redis sessions on suspension for tenant {tenant_id}: {rev_err}")

    return {"status": "success", "message": f"Tenant '{tenant.name}' status changed from '{old_status}' to '{tenant.status}'"}

@router.delete("/tenants/{tenant_id}")
@limiter.limit("10/minute", key_func=get_user_rate_limit_key)
def delete_tenant_organization(
    request: Request,
    tenant_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    from api.main import get_retriever

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant.id == 1:
        raise HTTPException(status_code=400, detail="Cannot delete default system organization")
    if tenant.id == current_admin.tenant_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own active organization")

    tenant_name = tenant.name

    # 0. Immediately revoke all active sessions for this tenant
    try:
        from src.sso.revocation import revoke_tenant_sessions
        revoke_tenant_sessions(tenant_id)
    except Exception as rev_err:
        logger.warning(f"Failed to revoke Redis sessions for deleted tenant {tenant_id}: {rev_err}")

    # 1. Purge all chunks from ChromaDB
    chunks_purged = 0
    r = get_retriever()
    if r and r._store:
        chunks_purged = r._store.delete_all_tenant_chunks(tenant_id)

    # 1b. Purge tenant Knowledge Graph (PostgreSQL + cached NetworkX)
    try:
        from src.graph import get_graph_store
        get_graph_store().delete_tenant_graph(tenant_id)
    except Exception as ge:
        logger.warning(f"Failed to purge Knowledge Graph for tenant {tenant_id}: {ge}")

    # 2. Purge distributed/local object storage prefix + legacy upload directory
    try:
        from src.storage import get_storage_provider
        storage = get_storage_provider()
        for obj_key in storage.list_objects(prefix=f"tenants/{tenant_id}/"):
            storage.delete_object(obj_key)
    except Exception as se:
        logger.warning(f"Failed to purge object storage for tenant {tenant_id}: {se}")

    tenant_dir = UPLOAD_DIR / f"tenant_{tenant_id}"
    if tenant_dir.exists():
        try:
            shutil.rmtree(tenant_dir)
        except Exception as e:
            logger.warning(f"Failed to remove directory for tenant {tenant_id}: {e}")

    # 3. Unlink circular superadmin FK and cascade delete all DB records
    tenant.superadmin_user_id = None
    db.flush()
    db.delete(tenant)
    db.commit()

    return {
        "status": "purged",
        "message": f"Organization '{tenant_name}' and all associated users, files, and vectors successfully deleted.",
        "chunks_purged": chunks_purged
    }

# ──────────────────────────────────────────────────────────────────
# GLOBAL REAL-TIME ACTIVITY STREAM
# ──────────────────────────────────────────────────────────────────

@router.get("/activity")
@limiter.limit("60/minute", key_func=get_user_rate_limit_key)
def get_global_activity_feed(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_platform_admin),
):
    query = db.query(ActivityLog)
    if category:
        query = query.filter(ActivityLog.category == category.upper())

    logs = query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()

    return [{
        "id": log.id,
        "tenant_id": log.tenant_id,
        "tenant_name": log.tenant.name if log.tenant else f"Tenant #{log.tenant_id}",
        "user_id": log.user_id,
        "username": log.user.username if log.user else "System",
        "action": log.action,
        "category": log.category,
        "description": log.description,
        "details": log.details,
        "timestamp": log.timestamp
    } for log in logs]
