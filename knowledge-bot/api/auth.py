from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging

from src.models import User, AccessRequest, Tenant
from api.dependencies import get_db, get_current_user
from src.auth import verify_password, get_password_hash, create_user_token
from src.activity import log_activity
from api.limiter import limiter, get_ip_rate_limit_key

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
    username: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None

class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str
    company_name: Optional[str] = None
    join_code: Optional[str] = None

class TenantDomainUpdate(BaseModel):
    allowed_domains: str

PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "mail.com", "proton.me", "protonmail.com",
    "aol.com", "zoho.com", "gmx.com", "yandex.com",
}

@router.post("/register", response_model=Token)
@limiter.limit("5/minute", key_func=get_ip_rate_limit_key)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
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
                    join_code=generate_join_code(),
                    monthly_token_budget=500000,
                    current_month_tokens=0,
                    budget_reset_at=datetime.utcnow()
                )
                db.add(tenant)
                db.flush()
                assigned_role = "superadmin"
            else:
                if tenant.status == "suspended":
                    raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
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
@limiter.limit("10/minute", key_func=get_ip_rate_limit_key)
def login(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
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

    # Block login if organization is suspended (unless platform admin)
    if user.tenant and user.tenant.status == "suspended" and not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization has been suspended. Please contact platform administrator.",
        )

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
        "allowed_domains": current_user.tenant.allowed_domains if current_user.tenant else None,
        "is_platform_admin": bool(current_user.is_platform_admin),
        "access_token": create_user_token(current_user)
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


# ──────────────────────────────────────────────────────────────────
# ENTERPRISE OAUTH2 & DOMAIN AUTO-ROUTING (PILLAR 8)
# ──────────────────────────────────────────────────────────────────

@router.get("/oauth/providers")
def get_oauth_providers():
    """Returns the availability status of OAuth2 providers."""
    from src.oauth import get_available_oauth_providers
    return get_available_oauth_providers()

@router.get("/oauth/{provider}/authorize")
def oauth_authorize(provider: str, redirect_uri: str):
    """Generates the provider authorization URL."""
    from src.oauth import generate_oauth_authorization_url
    try:
        url = generate_oauth_authorization_url(provider=provider, redirect_uri=redirect_uri)
        return {"authorization_url": url}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/oauth/{provider}/callback", response_model=Token)
def oauth_callback(provider: str, request: OAuthCallbackRequest, db: Session = Depends(get_db)):
    """
    Exchanges code for verified identity, matches corporate domain or provisions account,
    and returns enterprise multi-tenant JWT token.
    """
    from src.oauth import exchange_oauth_code
    from src.database import slugify, generate_join_code
    import re

    try:
        profile = exchange_oauth_code(
            provider=provider,
            code=request.code,
            redirect_uri=request.redirect_uri
        )
    except Exception as e:
        logger.error(f"OAuth code exchange failed: {e}")
        raise HTTPException(status_code=400, detail=f"OAuth verification failed: {str(e)}")

    email = profile.get("email")
    oauth_id = profile.get("oauth_id")
    name = profile.get("name") or "User"
    avatar_url = profile.get("avatar_url")

    # 1. Check if user already exists by email or provider sub
    existing_user = db.query(User).filter(
        (User.email == email) |
        ((User.auth_provider == provider) & (User.oauth_id == oauth_id))
    ).first()

    if existing_user:
        # Check suspended tenant
        if existing_user.tenant and existing_user.tenant.status == "suspended" and not existing_user.is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your organization has been suspended. Please contact platform administrator.",
            )

        # Update metadata if needed
        if not existing_user.avatar_url and avatar_url:
            existing_user.avatar_url = avatar_url
        if not existing_user.email:
            existing_user.email = email
        db.commit()
        db.refresh(existing_user)

        log_activity(
            tenant_id=existing_user.tenant_id or 1,
            user_id=existing_user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=f"User '{existing_user.username}' signed in via {provider.capitalize()} OAuth"
        )

        return {
            "access_token": create_user_token(existing_user),
            "token_type": "bearer",
            "role": existing_user.role,
            "tenant_id": existing_user.tenant_id,
            "tenant_name": existing_user.tenant.name if existing_user.tenant else None,
            "is_platform_admin": bool(existing_user.is_platform_admin),
            "username": existing_user.username,
            "email": existing_user.email,
            "avatar_url": existing_user.avatar_url,
        }

    # 2. User does not exist: Provision new user with Corporate Domain Auto-Routing
    tenant = None
    assigned_role = "user"
    email_domain = email.split("@")[-1].lower() if "@" in email else ""

    # 2a. Check if email domain matches an existing tenant's allowed_domains
    if email_domain and email_domain not in PUBLIC_EMAIL_DOMAINS:
        matching_tenants = db.query(Tenant).filter(Tenant.status == "active").all()
        for t in matching_tenants:
            if t.allowed_domains:
                domains = [d.strip().lower() for d in t.allowed_domains.split(",") if d.strip()]
                if email_domain in domains:
                    tenant = t
                    assigned_role = "user"
                    break

    # 2b. Explicit company_name or join_code from request
    if not tenant:
        if request.company_name and request.company_name.strip():
            company_clean = request.company_name.strip()
            slug = slugify(company_clean)
            tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
            if tenant is None:
                tenant = Tenant(
                    name=company_clean,
                    slug=slug,
                    status="active",
                    join_code=generate_join_code(),
                    allowed_domains=email_domain if email_domain not in PUBLIC_EMAIL_DOMAINS else None,
                    monthly_token_budget=500000,
                    current_month_tokens=0,
                    budget_reset_at=datetime.utcnow()
                )
                db.add(tenant)
                db.flush()
                assigned_role = "superadmin"
            else:
                if tenant.status == "suspended":
                    raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
                if not request.join_code or request.join_code.strip() != (tenant.join_code or "").strip():
                    raise HTTPException(status_code=403, detail="Invalid or missing join code for this organization")
                assigned_role = "user"
        elif request.join_code and request.join_code.strip():
            target_tenant = db.query(Tenant).filter(Tenant.join_code == request.join_code.strip()).first()
            if not target_tenant:
                raise HTTPException(status_code=400, detail="Invalid organization join code")
            if target_tenant.status == "suspended":
                raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
            tenant = target_tenant
            assigned_role = "user"
        else:
            # Fallback to Default Organization (Tenant #1)
            tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()
            if tenant and tenant.status == "suspended":
                raise HTTPException(status_code=403, detail="Default organization is suspended. Please contact platform administrator.")
            assigned_role = "user"

    # Synchronize PostgreSQL auto-increment sequences before user insertion
    from src.database import engine
    from sqlalchemy import text
    if engine.dialect.name == "postgresql":
        try:
            db.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
            db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
        except Exception as seq_err:
            logger.warning(f"OAuth sequence sync notice: {seq_err}")

    # Generate unique username from name or email
    base_user = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(" ", "_")).strip()
    if not base_user or len(base_user) < 3:
        base_user = email.split("@")[0].lower()
    base_user = re.sub(r'[^a-zA-Z0-9_]', '', base_user)[:20]

    unique_username = base_user
    counter = 1
    while db.query(User).filter(User.username == unique_username).first():
        unique_username = f"{base_user}_{counter}"
        counter += 1

    new_user = User(
        username=unique_username,
        email=email,
        auth_provider=provider,
        oauth_id=oauth_id,
        avatar_url=avatar_url,
        hashed_password=None,
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
            description=f"User '{new_user.username}' registered via {provider.capitalize()} OAuth in '{tenant.name}'"
        )

    return {
        "access_token": create_user_token(new_user),
        "token_type": "bearer",
        "role": new_user.role,
        "tenant_id": new_user.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "is_platform_admin": bool(new_user.is_platform_admin),
        "username": new_user.username,
        "email": new_user.email,
        "avatar_url": new_user.avatar_url,
    }

@router.get("/tenant/domains")
def get_tenant_domains(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns the allowed corporate email domains for the user's organization."""
    if not current_user.tenant_id:
        return {"allowed_domains": None}
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"allowed_domains": tenant.allowed_domains}

@router.patch("/tenant/domains")
def update_tenant_domains(update: TenantDomainUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Allows SuperAdmins and Admins to configure allowed email domains for 1-click corporate onboarding."""
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    raw_domains = (update.allowed_domains or "").strip().lower()
    if not raw_domains:
        tenant.allowed_domains = None
        db.commit()
        log_activity(
            tenant_id=tenant.id,
            user_id=current_user.id,
            action="TENANT_DOMAINS_CLEARED",
            category="GOVERNANCE",
            description="Cleared corporate domain restrictions (registration reverts to join code only)"
        )
        return {"status": "success", "allowed_domains": None}

    import re
    domain_list = [d.strip().lower() for d in raw_domains.split(",") if d.strip()]
    cleaned_domains = []

    for d in domain_list:
        if d in PUBLIC_EMAIL_DOMAINS:
            raise HTTPException(
                status_code=400,
                detail=f"Public consumer email domain '{d}' cannot be used for corporate identity auto-routing. Please specify a proprietary corporate domain."
            )
        if not re.match(r'^[a-z0-9.-]+\.[a-z]{2,}$', d) or ".." in d or d.startswith(".") or d.endswith("."):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid domain format: '{d}'. Expected standard hostname format (e.g. 'company.com')."
            )
        if d not in cleaned_domains:
            cleaned_domains.append(d)

    tenant.allowed_domains = ", ".join(cleaned_domains)
    db.commit()
    
    log_activity(
        tenant_id=tenant.id,
        user_id=current_user.id,
        action="TENANT_DOMAINS_UPDATED",
        category="GOVERNANCE",
        description=f"Configured allowed corporate domains: '{tenant.allowed_domains}'"
    )
    return {"status": "success", "allowed_domains": tenant.allowed_domains}

