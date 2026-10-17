from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
import logging

from src.models import User, AccessRequest, Tenant
from api.dependencies import get_db, get_current_user
from src.auth import verify_password, get_password_hash, create_user_token
from src.activity import log_activity

logger = logging.getLogger(__name__)
router = APIRouter()

class UserCreate(BaseModel):
    username: str
    password: str
    company_name: Optional[str] = None
    join_code: Optional[str] = None

class RoleRequest(BaseModel):
    role: str

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    is_platform_admin: bool = False

@router.post("/register", response_model=Token)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        # Synchronize postgres auto-increment sequences before insertions
        from src.database import slugify, generate_join_code, engine
        from sqlalchemy import text
        if engine.dialect.name == "postgresql":
            try:
                db.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
                db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
            except Exception as seq_err:
                logger.warning(f"Registration sequence sync notice: {seq_err}")

        db_user = db.query(User).filter(User.username == user_data.username).first()
        if db_user:
            raise HTTPException(status_code=400, detail="Username already registered")
        
        tenant = None
        assigned_role = "user"
        if user_data.company_name and user_data.company_name.strip():
            company_clean = user_data.company_name.strip()
            slug = slugify(company_clean)
            tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
            if tenant is None:
                tenant = Tenant(
                    name=company_clean,
                    slug=slug,
                    status="active",
                    join_code=generate_join_code()
                )
                db.add(tenant)
                db.flush()
                assigned_role = "superadmin"
            else:
                # Existing company requires valid join code
                if not user_data.join_code or user_data.join_code.strip() != (tenant.join_code or "").strip():
                    raise HTTPException(status_code=403, detail="Invalid or missing join code for this organization")
                assigned_role = "user"
        else:
            # Default tenant fallback
            tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()

        hashed_password = get_password_hash(user_data.password)
        new_user = User(
            username=user_data.username.strip(),
            hashed_password=hashed_password,
            role=assigned_role,
            tenant_id=tenant.id if tenant else None,
            is_platform_admin=False
        )
        db.add(new_user)
        db.flush()

        if tenant and assigned_role == "superadmin" and tenant.superadmin_user_id is None:
            tenant.superadmin_user_id = new_user.id

        db.commit()
        db.refresh(new_user)

        if tenant:
            log_activity(
                tenant_id=tenant.id,
                user_id=new_user.id,
                action="USER_REGISTER",
                category="AUTH",
                description=f"User '{new_user.username}' registered as '{assigned_role}' in '{tenant.name}'"
            )

        access_token = create_user_token(new_user)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": new_user.role,
            "tenant_id": new_user.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "is_platform_admin": bool(new_user.is_platform_admin)
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=400, detail=f"Registration failed: {str(e)}")

@router.post("/login", response_model=Token)
def login(user_data: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Ensure tenant_id is populated
    if user.tenant_id is None:
        default_tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()
        if default_tenant:
            user.tenant_id = default_tenant.id
            db.commit()
            db.refresh(user)

    tenant_name = user.tenant.name if user.tenant else None

    # Log successful login
    if user.tenant_id:
        log_activity(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=f"User '{user.username}' logged in"
        )

    access_token = create_user_token(user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant_name,
        "is_platform_admin": bool(user.is_platform_admin)
    }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "tenant_name": current_user.tenant.name if current_user.tenant else None,
        "tenant_slug": current_user.tenant.slug if current_user.tenant else None,
        "is_platform_admin": bool(current_user.is_platform_admin)
    }

@router.post("/request_role")
def request_role(role_req: RoleRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if role_req.role not in ["editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role requested")
    
    # Check if already requested in this tenant
    existing = db.query(AccessRequest).filter(
        AccessRequest.user_id == current_user.id,
        AccessRequest.tenant_id == current_user.tenant_id,
        AccessRequest.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending role request")
        
    req = AccessRequest(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        requested_role=role_req.role
    )
    db.add(req)
    db.commit()

    if current_user.tenant_id:
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="ROLE_REQUEST",
            category="GOVERNANCE",
            description=f"User '{current_user.username}' requested promotion to '{role_req.role}'"
        )

    return {"status": "success"}

@router.get("/my_request")
def my_request(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    req = db.query(AccessRequest).filter(
        AccessRequest.user_id == current_user.id,
        AccessRequest.tenant_id == current_user.tenant_id
    ).order_by(AccessRequest.created_at.desc()).first()
    if req:
        return {"requested_role": req.requested_role, "status": req.status}
    return None
